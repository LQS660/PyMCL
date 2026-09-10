using System.Text;

namespace PyMCL.Services;

public sealed class TaskRow
{
    public string Id { get; init; } = "";
    public string Title { get; set; } = "";
    public string Status { get; set; } = "排队中…";
    public string Speed { get; set; } = "";
    public double Progress { get; set; }
    public bool Indeterminate { get; set; } = true;
    public bool Finished { get; set; }
    public bool Success { get; set; }
    public DateTime Started { get; } = DateTime.Now;
    public StringBuilder Log { get; } = new();
    public int LogLines;

    public void Append(string line)
    {
        if (string.IsNullOrEmpty(line)) return;
        Log.AppendLine(line);
        LogLines++;
        if (LogLines <= 600) return;
        // 单任务日志上限，长下载不至于把内存吃光。
        var text = Log.ToString();
        var cut = text.IndexOf('\n', text.Length / 3);
        Log.Clear();
        Log.Append(cut > 0 ? text[(cut + 1)..] : text);
        LogLines = 400;
    }
}

/// <summary>任务总线。下载坞、任务页、侧栏徽章都读这一份。</summary>
public static class TaskStore
{
    private static readonly List<TaskRow> _rows = new();

    public static IReadOnlyList<TaskRow> Rows => _rows;
    public static event Action<TaskRow>? Added;
    public static event Action<TaskRow>? Updated;
    public static event Action? Cleared;

    public static int RunningCount => _rows.Count(r => !r.Finished);

    public static TaskRow? Get(string id) => _rows.FirstOrDefault(r => r.Id == id);

    public static TaskRow? Newest => _rows.LastOrDefault(r => !r.Finished) ?? _rows.LastOrDefault();

    public static void Handle(BridgeEvent ev)
    {
        switch (ev.Event)
        {
            case "task_added":
            {
                if (string.IsNullOrEmpty(ev.TaskId) || Get(ev.TaskId) != null) return;
                var row = new TaskRow { Id = ev.TaskId, Title = string.IsNullOrEmpty(ev.Title) ? "任务" : ev.Title };
                _rows.Add(row);
                if (_rows.Count > 60) _rows.RemoveRange(0, _rows.Count - 60);
                Added?.Invoke(row);
                break;
            }
            case "progress":
            {
                var row = Get(ev.TaskId);
                if (row is null) return;
                Fmt.SplitMsg(ev.Message, out var st, out var sp);
                row.Status = string.IsNullOrEmpty(st) ? row.Status : st;
                row.Speed = sp;
                row.Indeterminate = ev.Total <= 0;
                if (ev.Total > 0) row.Progress = Math.Clamp(ev.Current * 100.0 / ev.Total, 0, 100);
                Updated?.Invoke(row);
                break;
            }
            case "log":
            {
                var row = Get(ev.TaskId);
                if (row is null) return;
                row.Append(ev.Text);
                Updated?.Invoke(row);
                break;
            }
            case "finished":
            {
                var row = Get(ev.TaskId);
                if (row is null) return;
                row.Finished = true;
                row.Success = ev.Success;
                row.Indeterminate = false;
                row.Progress = ev.Success ? 100 : row.Progress;
                row.Status = string.IsNullOrEmpty(ev.Message) ? (ev.Success ? "已完成" : "失败") : ev.Message;
                row.Speed = "";
                Updated?.Invoke(row);
                break;
            }
        }
    }

    public static void ClearFinished()
    {
        _rows.RemoveAll(r => r.Finished);
        Cleared?.Invoke();
    }
}
