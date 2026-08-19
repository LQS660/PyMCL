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

    public TasksPage()
    {
        InitializeComponent();
    }

    public string? TitleOf(string taskId) => _titles.TryGetValue(taskId, out var t) ? t : null;

    public void HandleEvent(BridgeEvent ev)
    {
        if (ev.Event == "task_added" && !string.IsNullOrEmpty(ev.TaskId))
        {
            Empty.Visibility = Visibility.Collapsed;
            var card = new TaskCardUi(ev.TaskId, ev.Title);
            _cards[ev.TaskId] = card;
            _titles[ev.TaskId] = ev.Title;
            Motion.CardEnter(card.Root, 0);
            ListHost.Children.Add(card.Root);
        }
        else if (ev.Event == "progress" && _cards.TryGetValue(ev.TaskId, out var p))
            p.SetProgress(ev.Current, ev.Total, ev.Message);
        else if (ev.Event == "log" && _cards.TryGetValue(ev.TaskId, out var l) && !string.IsNullOrEmpty(ev.Text))
            l.AppendLog(ev.Text);
        else if (ev.Event == "finished" && _cards.TryGetValue(ev.TaskId, out var f))
            f.SetFinished(ev.Success, ev.Message);
    }

    private sealed class TaskCardUi
    {
        public Border Root { get; }
        private readonly ProgressBar _bar = new() { Minimum = 0, Maximum = 100, Foreground = new SolidColorBrush(Color.FromArgb(255, 46, 155, 107)) };
        private readonly TextBlock _status = new() { Text = "排队中…", Foreground = new SolidColorBrush(Color.FromArgb(255, 136, 136, 136)), FontSize = 12 };
        private readonly TextBlock _speed = new() { Foreground = new SolidColorBrush(Color.FromArgb(255, 136, 136, 136)), FontSize = 12 };
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

        public void AppendLog(string text)
        {
            _log.Text += text + "\n";
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
            if (!string.IsNullOrEmpty(message)) _log.Text += message + "\n";
        }
    }
}
