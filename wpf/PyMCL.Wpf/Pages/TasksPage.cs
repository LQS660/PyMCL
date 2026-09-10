using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class TasksPage : PageBase
{
    public override string Title => "下载任务";

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
    }

    public TasksPage()
    {
        var clear = Ui.Btn("清除已完成", BtnKind.Chip, (_, _) =>
        {
            TaskStore.ClearFinished();
            Rebuild();
        }, Ico.Broom);
        var head = Ui.Section("下载任务", "安装、下载、启动都在这里排队", Ui.H(8, _summary.VCenter(), clear));
        Content = ScrollBody(head, _list);
        TaskStore.Added += _ => Dispatcher.Invoke(Rebuild);
        TaskStore.Updated += r => Dispatcher.Invoke(() => Sync(r));
        TaskStore.Cleared += () => Dispatcher.Invoke(Rebuild);
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
        _summary.Text = rows.Count == 0 ? "" : $"进行中 {TaskStore.RunningCount} · 共 {rows.Count}";
        if (rows.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.Download, "还没有任务", "去下载页装个版本或模组试试"));
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
    }

    private Card Build(TaskRow row)
    {
        var title = Ui.Txt(row.Title, 13.5, true).Trim();
        var status = Ui.Muted("");
        var speed = Ui.Small("");
        var bar = Ui.Prog();
        var cancel = Ui.Btn("取消", BtnKind.Ghost);
        var toggle = Ui.Btn("日志", BtnKind.Chip, glyph: Ico.List);
        var crash = Ui.Btn("崩溃分析", BtnKind.Chip, glyph: Ico.Bug);
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

        cancel.Click += async (_, _) =>
        {
            cancel.IsEnabled = false;
            await Api.TryCallAsync<object>("cancel_task", new { task_id = row.Id });
        };
        crash.Click += (_, _) => Run(async () =>
        {
            var report = await Api.TryCallAsync<CrashReport>("get_crash", new { task_id = row.Id });
            if (report is null || string.IsNullOrWhiteSpace(report.Title + report.Headline + report.Summary + report.Detail))
            {
                Toast("没有崩溃分析", "这个任务没有留下崩溃报告", ToastKind.Info);
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
        c.Cancel.Content = row.Finished ? (row.Success ? "已完成" : "已结束") : "取消";
        c.Crash.Show(row.Finished && !row.Success);
        c.Bar.Foreground = row.Finished && !row.Success ? Ui.Res("B.Danger") : Ui.Res("B.Accent");
        if (c.Expanded)
        {
            var atEnd = c.Log.VerticalOffset >= c.Log.ExtentHeight - c.Log.ViewportHeight - 20;
            c.Log.Text = row.Log.ToString();
            if (atEnd) c.Log.ScrollToEnd();
        }
        _summary.Text = $"进行中 {TaskStore.RunningCount} · 共 {TaskStore.Rows.Count}";
    }
}
