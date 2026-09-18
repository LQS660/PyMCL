using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class TasksPage : PageBase
{
    public override string Title => L("下载任务");

    private readonly SPanel _list = Ui.V(10);
    private readonly Dictionary<string, Card> _cards = new();
    private readonly TextBlock _summary = Ui.Muted("");

    private sealed class Card
    {
        public required Border Root { get; init; }
        public required TextBlock Title { get; init; }
        public required TextBlock Status { get; init; }
        public required TextBlock Speed { get; init; }
        public required ProgressBar Bar { get; init; }
        public required Button Cancel { get; init; }
        public required Button Toggle { get; init; }
        public required Button Crash { get; init; }
        public required Border LogWrap { get; init; }
        public required TextBox Log { get; init; }
        public bool Expanded;
        public DateTime LogPainted;
    }

    public TasksPage()
    {
        var clear = Ui.Btn(L("清除已完成"), BtnKind.Chip, (_, _) =>
        {
            TaskStore.ClearFinished();
            Rebuild();
        }, Ico.Broom);
        var head = Ui.Section(L("下载任务"), L("安装、下载、启动都在这里排队"), Ui.H(8, _summary.VCenter(), clear));
        Content = ScrollBody(head, _list);
        // 下载中心：拖什么都收，按内容认类型，装进默认实例
        EnableDrop(() => FileDrop.DropContext.None);
        // 事件是 SSE 读取线程送来的，下载期间每秒几十条。用 BeginInvoke 把渲染排进队列即可，
        // 换成同步 Invoke 会让读取线程停在这儿等 UI 画完，事件流跟着一起被拖慢。
        TaskStore.Added += _ => Dispatcher.BeginInvoke(Rebuild);
        TaskStore.Updated += r => Dispatcher.BeginInvoke(() => Sync(r));
        TaskStore.Cleared += () => Dispatcher.BeginInvoke(Rebuild);
    }

    protected override Task LoadAsync()
    {
        Rebuild();
        return Task.CompletedTask;
    }

    public override void OnShown() => Rebuild();

    private void Rebuild()
    {
        _list.Children.Clear();
        _cards.Clear();
        var rows = TaskStore.Rows.Reverse().ToList();
        _summary.Text = rows.Count == 0 ? "" : L("进行中 {0} · 共 {1}", TaskStore.RunningCount, rows.Count);
        if (rows.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.Download, L("还没有任务"), L("去下载页装个版本或模组试试")));
            return;
        }
        foreach (var r in rows)
        {
            var card = Build(r);
            _cards[r.Id] = card;
            _list.Children.Add(card.Root);
            Sync(r);
        }
        Motion.Stagger(_list, 24);
        Run(ResolveTitlesAsync);
    }

    /// <summary>
    /// 界面连上之前就已经在跑的任务，task_added 事件没赶上，标题只能先占个「任务」。
    /// 桥自己记着每条任务的标题，问它一次补回来。
    /// </summary>
    private async Task ResolveTitlesAsync()
    {
        foreach (var row in TaskStore.Rows.Where(r => r.Title == TaskStore.PlaceholderTitle).ToList())
        {
            var title = await Api.TryCallAsync<string>("task_title", new { task_id = row.Id }, "") ?? "";
            if (title.Length == 0 || title == row.Id || title == row.Title) continue;
            row.Title = title;
            if (_cards.TryGetValue(row.Id, out var card)) card.Title.Text = title;
        }
    }

    private Card Build(TaskRow row)
    {
        var title = Ui.Txt(row.Title, 13.5, true).Trim();
        var status = Ui.Muted("");
        var speed = Ui.Small("");
        var bar = Ui.Prog();
        var cancel = Ui.Btn(L("取消"), BtnKind.Ghost);
        var toggle = Ui.Btn(L("日志"), BtnKind.Chip, glyph: Ico.List);
        var crash = Ui.Btn(L("崩溃分析"), BtnKind.Chip, glyph: Ico.Bug);
        crash.Visibility = Visibility.Collapsed;
        var log = Ui.LogBox();
        log.Height = 160;
        log.BorderThickness = new Thickness(0);
        log.Background = Brushes.Transparent;
        var logWrap = Ui.Pane(log, radius: 9, padding: 10);
        logWrap.Visibility = Visibility.Collapsed;

        var top = Ui.G(null, "*,Auto");
        top.Add(Ui.V(3, title, status).VCenter(), 0, 0);
        top.Add(Ui.H(6, crash, toggle, cancel).VCenter(), 0, 1);

        var bottom = Ui.G(null, "*,Auto");
        bottom.Add(bar.VCenter(), 0, 0);
        bottom.Add(speed.M(10, 0, 0, 0).VCenter(), 0, 1);

        var body = Ui.V(9, top, bottom, logWrap);
        var root = Ui.Card(body, 14);
        Motion.HoverLift(root, 1.004, 1, 16);

        var card = new Card
        {
            Root = root, Title = title, Status = status, Speed = speed,
            Bar = bar, Cancel = cancel, Toggle = toggle, Crash = crash, LogWrap = logWrap, Log = log,
        };

        cancel.Click += (_, _) => Run(async () =>
        {
            cancel.IsEnabled = false;
            await Api.TryCallAsync<object>("cancel_task", new { task_id = row.Id });
        });
        crash.Click += (_, _) => Run(async () =>
        {
            var report = await Api.TryCallAsync<CrashReport>("get_crash", new { task_id = row.Id });
            if (report is null || string.IsNullOrWhiteSpace(report.Title + report.Headline + report.Summary + report.Detail))
            {
                Toast(L("没有崩溃分析"), L("这个任务没有留下崩溃报告"), ToastKind.Info);
                return;
            }
            if (string.IsNullOrEmpty(report.TaskId)) report.TaskId = row.Id;
            await CrashUi.ShowAsync(report);
        });
        toggle.Click += (_, _) =>
        {
            card.Expanded = !card.Expanded;
            if (card.Expanded)
            {
                card.Log.Text = row.Log.ToString();
                card.Log.ScrollToEnd();
                logWrap.Visibility = Visibility.Visible;
                Motion.FadeIn(logWrap, 200, 8);
            }
            else logWrap.Visibility = Visibility.Collapsed;
        };
        return card;
    }

    private void Sync(TaskRow row)
    {
        if (!_cards.TryGetValue(row.Id, out var c))
        {
            Rebuild();
            return;
        }
        c.Title.Text = row.Title;
        c.Status.Text = row.Status;
        c.Speed.Text = row.Speed;
        c.Bar.IsIndeterminate = row.Indeterminate && !row.Finished;
        if (!c.Bar.IsIndeterminate) Motion.Progress(c.Bar, row.Progress);
        c.Cancel.IsEnabled = !row.Finished;
        c.Cancel.Content = row.Finished ? (row.Success ? L("已完成") : L("已结束")) : L("取消");
        c.Crash.Show(row.Finished && !row.Success);
        c.Bar.Foreground = row.Finished && !row.Success ? Ui.Res("B.Danger") : Ui.Res("B.Accent");
        // 展开的日志每来一行就 StringBuilder.ToString() 一次，几百行的下载日志等于每秒重排几十遍
        // 整块文本。限到 10Hz，任务结束时再补最后一次，看起来一样、开销降一个数量级。
        if (c.Expanded && (row.Finished || DateTime.UtcNow - c.LogPainted >= LogInterval))
        {
            c.LogPainted = DateTime.UtcNow;
            var atEnd = c.Log.VerticalOffset >= c.Log.ExtentHeight - c.Log.ViewportHeight - 20;
            c.Log.Text = row.Log.ToString();
            if (atEnd) c.Log.ScrollToEnd();
        }
        _summary.Text = L("进行中 {0} · 共 {1}", TaskStore.RunningCount, TaskStore.Rows.Count);
    }

    private static readonly TimeSpan LogInterval = TimeSpan.FromMilliseconds(100);
}
