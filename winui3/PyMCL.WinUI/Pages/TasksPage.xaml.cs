using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using PyMCL.Models;
using PyMCL.Services;
using Windows.UI;

namespace PyMCL.Pages;

public sealed partial class TasksPage : UserControl
{
    private readonly Dictionary<string, TaskCardUi> _cards = new();
    private readonly Dictionary<string, string> _titles = new();
    private readonly HashSet<string> _done = new();

    public TasksPage()
    {
        InitializeComponent();
    }

    public string? TitleOf(string taskId) => _titles.TryGetValue(taskId, out var t) ? t : null;

    public void HandleEvent(BridgeEvent ev)
    {
        if (ev.Event == "task_added" && !string.IsNullOrEmpty(ev.TaskId))
        {
            // 「启动游戏」「微软登录」不是下载任务，列在下载任务页里只会误导用户。
            // PySide6 两处都特意过滤掉了，这里以前一个都没挡。
            if (MainWindow.IsSilentTask(ev.Title)) return;
            var card = new TaskCardUi(ev.TaskId, ev.Title);
            _cards[ev.TaskId] = card;
            _titles[ev.TaskId] = ev.Title;
            Motion.CardEnter(card.Root, 0);
            ListHost.Children.Add(card.Root);
            SyncChrome();
        }
        else if (ev.Event == "progress" && _cards.TryGetValue(ev.TaskId, out var p))
            p.SetProgress(ev.Current, ev.Total, ev.Message);
        else if (ev.Event == "log" && _cards.TryGetValue(ev.TaskId, out var l) && !string.IsNullOrEmpty(ev.Text))
            l.AppendLog(ev.Text);
        else if (ev.Event == "finished" && _cards.TryGetValue(ev.TaskId, out var f))
        {
            f.SetFinished(ev.Success, ev.Message);
            _done.Add(ev.TaskId);
            SyncChrome();
        }
    }

    /// <summary>
    /// 卡片以前只增不减，也没有清除入口，开着用一天列表就无限长。
    /// 这里补上「清除已完成」，顺便让空状态在清空后能重新出现
    /// （原来 Empty 一旦隐藏就再也回不来，删完是一片空白）。
    /// </summary>
    private void ClearDone_Click(object sender, RoutedEventArgs e)
    {
        foreach (var taskId in _done.ToList())
        {
            if (_cards.Remove(taskId, out var card))
                ListHost.Children.Remove(card.Root);
            _titles.Remove(taskId);
        }
        _done.Clear();
        SyncChrome();
    }

    private void SyncChrome()
    {
        Empty.Visibility = _cards.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        ClearDone.IsEnabled = _done.Count > 0;
    }

    private sealed class TaskCardUi
    {
        public Border Root { get; }

        // 以前这三处写死 #2E9B6B / #888888，不跟主题走：深色下 #888 压深色卡片对比度不足。
        // 改用主题笔刷，浅色深色和高对比度都由 Styles/Theme.xaml 统一给。
        private static Brush Res(string key) => (Brush)Application.Current.Resources[key];

        private readonly ProgressBar _bar = new() { Minimum = 0, Maximum = 100, Foreground = Res("AccentFillColorDefaultBrush") };
        private readonly TextBlock _status = new() { Text = "排队中…", Foreground = Res("TextFillColorSecondaryBrush"), FontSize = 12 };
        private readonly TextBlock _speed = new() { Foreground = Res("TextFillColorSecondaryBrush"), FontSize = 12 };
        private readonly TextBox _log = new() { IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, Height = 240, Visibility = Visibility.Collapsed, FontSize = 12 };
        private readonly Button _cancel;
        private bool _expanded;

        public TaskCardUi(string taskId, string title)
        {
            _expanded = title.Contains("整合包");
            _log.Visibility = _expanded ? Visibility.Visible : Visibility.Collapsed;
            Root = new Border
            {
                MinHeight = 96, Padding = new Thickness(16, 12, 16, 12),
                Background = (Brush)Application.Current.Resources["CardBackgroundFillColorDefaultBrush"],
                BorderBrush = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"],
                BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8),
                Translation = new System.Numerics.Vector3(0, 0, 16),
                Shadow = new ThemeShadow(),
            };
            var col = new StackPanel { Spacing = 8 };
            var top = new Grid();
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            top.Children.Add(new TextBlock { Text = title, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
            var toggle = new Button { Content = _expanded ? "▴" : "▾", Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent), BorderThickness = new Thickness(0), Width = 32 };
            toggle.Click += (_, _) =>
            {
                _expanded = !_expanded;
                _log.Visibility = _expanded ? Visibility.Visible : Visibility.Collapsed;
                toggle.Content = _expanded ? "▴" : "▾";
            };
            Grid.SetColumn(toggle, 1);
            _cancel = new Button { Content = "✕", Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent), BorderThickness = new Thickness(0), Width = 32 };
            _cancel.Click += async (_, _) =>
            {
                try { await AppServices.Client.CallAsync("cancel_task", new { task_id = taskId }); } catch { }
                _status.Text = "正在取消…";
                _cancel.IsEnabled = false;
            };
            Grid.SetColumn(_cancel, 2);
            top.Children.Add(toggle);
            top.Children.Add(_cancel);
            col.Children.Add(top);
            col.Children.Add(_bar);
            var st = new Grid();
            st.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            st.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            st.Children.Add(_status);
            Grid.SetColumn(_speed, 1);
            st.Children.Add(_speed);
            col.Children.Add(st);
            col.Children.Add(_log);
            Root.Child = col;
        }

        public void SetProgress(int current, int total, string message)
        {
            if (total > 0) _bar.Value = current * 100.0 / total;
            MainWindow.SplitMsg(message, out var st, out var sp);
            _status.Text = string.IsNullOrEmpty(st) ? "处理中…" : st;
            _speed.Text = sp;
        }

        private const int LogMaxLines = 2500;
        private readonly List<string> _logLines = new();

        /// <summary>
        /// 裸 <c>_log.Text +=</c> 是 O(n²) 拼接且没有上限，装大整合包上千行日志会明显卡顿。
        /// 与 PySide6 的 setMaximumBlockCount(2500) 对齐。
        /// </summary>
        public void AppendLog(string text)
        {
            if (string.IsNullOrEmpty(text)) return;
            _logLines.Add(text);
            if (_logLines.Count > LogMaxLines)
                _logLines.RemoveRange(0, _logLines.Count - LogMaxLines);
            _log.Text = string.Join('\n', _logLines);
        }

        public void SetFinished(bool success, string message)
        {
            _cancel.IsEnabled = false;
            if (success)
            {
                _bar.Value = 100;
                _status.Text = "✔ " + message;
            }
            else
            {
                _status.Text = "✘ " + message;
                if (!_expanded)
                {
                    _expanded = true;
                    _log.Visibility = Visibility.Visible;
                }
            }
            _speed.Text = "";
            AppendLog(message);
        }
    }
}
