using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed class DashCard
{
    public string Type { get; set; } = "";
    public double X { get; set; }
    public double Y { get; set; }
    public double W { get; set; } = 0.3;
    public double H { get; set; } = 0.3;
}

public sealed class DashLayout
{
    public string Name { get; set; } = "默认";
    public int Grid { get; set; } = 24;
    public bool Snap { get; set; } = true;
    public List<DashCard> Cards { get; set; } = new();

    public DashLayout Clone() => new()
    {
        Name = Name, Grid = Grid, Snap = Snap,
        Cards = Cards.Select(c => new DashCard { Type = c.Type, X = c.X, Y = c.Y, W = c.W, H = c.H }).ToList(),
    };
}

public sealed class DashStore
{
    public int Active { get; set; }
    public List<DashLayout> Layouts { get; set; } = new();

    public static DashStore Default() => new()
    {
        Active = 0,
        Layouts = new List<DashLayout> { DefaultLayout("默认") },
    };

    public static DashLayout DefaultLayout(string name) => new()
    {
        Name = name,
        Cards = new List<DashCard>
        {
            new() { Type = "banner", X = 0, Y = 0, W = 1, H = 0.28 },
            new() { Type = "config", X = 0, Y = 0.30, W = 0.38, H = 0.70 },
            new() { Type = "log", X = 0.39, Y = 0.30, W = 0.61, H = 0.44 },
            new() { Type = "news", X = 0.39, Y = 0.76, W = 0.31, H = 0.24 },
            new() { Type = "quick", X = 0.71, Y = 0.76, W = 0.29, H = 0.24 },
        },
    };

    public DashLayout Current => Layouts.Count == 0
        ? Layouts.FirstOrDefault() ?? DefaultLayout("默认")
        : Layouts[Math.Clamp(Active, 0, Layouts.Count - 1)];

    public string ToJson() => JsonSerializer.Serialize(this, JsonOpt);

    public static DashStore FromJson(string json)
    {
        if (string.IsNullOrWhiteSpace(json)) return Default();
        try
        {
            var s = JsonSerializer.Deserialize<DashStore>(json, JsonOpt);
            if (s is null || s.Layouts.Count == 0) return Default();
            foreach (var l in s.Layouts)
                if (l.Cards.Count == 0) l.Cards.AddRange(DefaultLayout(l.Name).Cards);
            return s;
        }
        catch { return Default(); }
    }

    private static readonly JsonSerializerOptions JsonOpt = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}

/// <summary>
/// 自由画布。卡片坐标是 0~1 归一化的，窗口怎么缩放都按比例走；
/// 编辑态下可拖动、八向缩放、网格吸附。
/// </summary>
public sealed class DashHost : Panel
{
    private const double MinPxW = 190;
    private const double MinPxH = 96;
    private const double Gap = 10;

    private readonly Dictionary<string, FrameworkElement> _contents = new();
    private readonly List<CardView> _views = new();
    private readonly Border _gridLayer = new();
    private DashLayout _layout = DashStore.DefaultLayout("默认");
    private bool _edit;

    public event Action? Changed;
    public Func<string, UIElement?>? ContentFactory;
    public Func<string, string>? TitleFactory;

    public DashLayout Layout => _layout;

    public bool EditMode
    {
        get => _edit;
        set
        {
            if (_edit == value) return;
            _edit = value;
            foreach (var v in _views) v.SetEdit(value);
            _gridLayer.Visibility = value && _layout.Snap ? Visibility.Visible : Visibility.Collapsed;
            InvalidateArrange();
        }
    }

    public DashHost()
    {
        ClipToBounds = false;
        _gridLayer.Visibility = Visibility.Collapsed;
        _gridLayer.IsHitTestVisible = false;
        Children.Add(_gridLayer);
    }

    public void Load(DashLayout layout)
    {
        _layout = layout;
        Rebuild();
    }

    public void Rebuild()
    {
        foreach (var v in _views) Children.Remove(v);
        _views.Clear();
        foreach (var card in _layout.Cards)
        {
            var view = new CardView(this, card);
            var content = Cached(card.Type);
            view.SetContent(TitleFactory?.Invoke(card.Type) ?? card.Type, content);
            view.SetEdit(_edit);
            _views.Add(view);
            Children.Add(view);
        }
        UpdateGridLayer();
        InvalidateArrange();
        if (Motion.Enabled) Motion.StaggerItems(_views, 30, 220, 12);
    }

    /// <summary>卡片内容只造一次，切方案 / 重排都复用，避免日志和输入被重置。</summary>
    private UIElement? Cached(string type)
    {
        if (_contents.TryGetValue(type, out var el)) return el;
        var made = ContentFactory?.Invoke(type) as FrameworkElement;
        if (made is null) return null;
        _contents[type] = made;
        return made;
    }

    public void AddCard(string type)
    {
        if (_layout.Cards.Any(c => c.Type == type)) return;
        _layout.Cards.Add(new DashCard { Type = type, X = 0.05, Y = 0.05, W = 0.36, H = 0.34 });
        Rebuild();
        Changed?.Invoke();
    }

    public void RemoveCard(DashCard card)
    {
        _layout.Cards.Remove(card);
        Rebuild();
        Changed?.Invoke();
    }

    public bool Has(string type) => _layout.Cards.Any(c => c.Type == type);

    public void NotifyChanged() => Changed?.Invoke();

    private void UpdateGridLayer()
    {
        if (_layout.Grid <= 1)
        {
            _gridLayer.Background = null;
            return;
        }
        var step = 1.0 / _layout.Grid;
        var brush = new DrawingBrush
        {
            TileMode = TileMode.Tile,
            Viewport = new Rect(0, 0, step, step),
            ViewportUnits = BrushMappingMode.RelativeToBoundingBox,
            Drawing = new GeometryDrawing
            {
                Geometry = new RectangleGeometry(new Rect(0, 0, 10, 10)),
                Pen = new Pen(new SolidColorBrush(Color.FromArgb(38, 46, 155, 107)), 0.6),
            },
            Opacity = 0.9,
        };
        _gridLayer.Background = brush;
    }

    public double SnapV(double v)
    {
        if (!_layout.Snap || _layout.Grid <= 1) return Math.Clamp(v, 0, 1);
        var step = 1.0 / _layout.Grid;
        return Math.Clamp(Math.Round(v / step) * step, 0, 1);
    }

    protected override Size MeasureOverride(Size available)
    {
        var w = double.IsInfinity(available.Width) ? 900 : available.Width;
        var h = double.IsInfinity(available.Height) ? 600 : available.Height;
        foreach (UIElement c in Children)
        {
            if (c == _gridLayer) { c.Measure(available); continue; }
            if (c is CardView v) c.Measure(new Size(Math.Max(1, v.Card.W * w), Math.Max(1, v.Card.H * h)));
        }
        return new Size(w, h);
    }

    protected override Size ArrangeOverride(Size final)
    {
        _gridLayer.Arrange(new Rect(0, 0, final.Width, final.Height));
        foreach (var v in _views)
        {
            var r = new Rect(
                v.Card.X * final.Width,
                v.Card.Y * final.Height,
                Math.Max(40, v.Card.W * final.Width - Gap),
                Math.Max(30, v.Card.H * final.Height - Gap));
            v.Arrange(r);
        }
        return final;
    }

    public void BringToTop(CardView v)
    {
        Children.Remove(v);
        Children.Add(v);
    }

    // ---------------- 卡片外壳 ----------------
    public sealed class CardView : Border
    {
        private static readonly (string Name, double Cx, double Cy)[] Handles =
        {
            ("nw", 0, 0), ("n", 0.5, 0), ("ne", 1, 0),
            ("w", 0, 0.5), ("e", 1, 0.5),
            ("sw", 0, 1), ("s", 0.5, 1), ("se", 1, 1),
        };

        private readonly DashHost _host;
        private readonly Grid _root = new();
        private readonly Border _shell;
        private readonly Canvas _handleLayer = new();
        private readonly Border _editMask;
        private readonly TextBlock _title = Ui.Txt("", 12.5, true);
        private readonly Button _close;
        private readonly ContentControl _body = new() { Focusable = false };
        private bool _edit;
        private Point _grabPoint;
        private Rect _grabRect;
        private string? _mode;

        public DashCard Card { get; }

        public CardView(DashHost host, DashCard card)
        {
            _host = host;
            Card = card;
            _shell = new Border
            {
                CornerRadius = new CornerRadius(12),
                BorderThickness = new Thickness(1),
                ClipToBounds = true,
            };
            _shell.SetResourceReference(BackgroundProperty, "B.Paper");
            _shell.SetResourceReference(BorderBrushProperty, "B.Line");
            Motion.Shadow(_shell, 16, 0.07, 3);

            _close = Ui.IconBtn(Ico.Close, "移除卡片", (_, _) => _host.RemoveCard(Card), 11);
            _close.Padding = new Thickness(4);
            var head = Ui.G(null, "*,Auto");
            head.Add(_title.VCenter(), 0, 0);
            head.Add(_close, 0, 1);
            head.Margin = new Thickness(14, 10, 8, 6);

            var inner = Ui.G("Auto,*");
            inner.Add(head, 0, 0);
            inner.Add(new Border { Padding = new Thickness(14, 0, 14, 12), Child = _body }, 1, 0);
            _shell.Child = inner;

            _editMask = new Border
            {
                CornerRadius = new CornerRadius(12),
                BorderThickness = new Thickness(1.4),
                Visibility = Visibility.Collapsed,
                Background = new SolidColorBrush(Color.FromArgb(10, 46, 155, 107)),
                Cursor = Cursors.SizeAll,
            };
            _editMask.SetResourceReference(BorderBrushProperty, "B.Accent");
            _editMask.MouseLeftButtonDown += OnGrabMove;
            _editMask.MouseMove += OnDragMove;
            _editMask.MouseLeftButtonUp += OnDrop;

            _handleLayer.Visibility = Visibility.Collapsed;
            foreach (var h in Handles) _handleLayer.Children.Add(MakeHandle(h.Name));

            _root.Children.Add(_shell);
            _root.Children.Add(_editMask);
            _root.Children.Add(_handleLayer);
            Child = _root;
        }

        public void SetContent(string title, UIElement? content)
        {
            _title.Text = title;
            if (content is FrameworkElement fe && fe.Parent is ContentControl cc && cc != _body) cc.Content = null;
            _body.Content = content;
        }

        public void SetEdit(bool edit)
        {
            _edit = edit;
            _editMask.Visibility = edit ? Visibility.Visible : Visibility.Collapsed;
            _handleLayer.Visibility = edit ? Visibility.Visible : Visibility.Collapsed;
            _close.Visibility = edit ? Visibility.Visible : Visibility.Collapsed;
            _body.IsHitTestVisible = !edit;
        }

        private Border MakeHandle(string name)
        {
            var b = new Border
            {
                Width = 11, Height = 11,
                CornerRadius = new CornerRadius(3),
                BorderThickness = new Thickness(1.5),
                Cursor = name switch
                {
                    "n" or "s" => Cursors.SizeNS,
                    "e" or "w" => Cursors.SizeWE,
                    "nw" or "se" => Cursors.SizeNWSE,
                    _ => Cursors.SizeNESW,
                },
                Tag = name,
            };
            b.SetResourceReference(BackgroundProperty, "B.Paper");
            b.SetResourceReference(BorderBrushProperty, "B.Accent");
            b.MouseLeftButtonDown += (s, e) =>
            {
                _mode = (string)((Border)s).Tag;
                Grab(e);
            };
            b.MouseMove += OnDragMove;
            b.MouseLeftButtonUp += OnDrop;
            return b;
        }

        private void OnGrabMove(object sender, MouseButtonEventArgs e)
        {
            _mode = "move";
            Grab(e);
        }

        private void Grab(MouseButtonEventArgs e)
        {
            _host.BringToTop(this);
            _grabPoint = e.GetPosition(_host);
            _grabRect = new Rect(Card.X, Card.Y, Card.W, Card.H);
            ((UIElement)e.Source).CaptureMouse();
            e.Handled = true;
        }

        private void OnDragMove(object sender, MouseEventArgs e)
        {
            if (_mode is null || e.LeftButton != MouseButtonState.Pressed) return;
            var p = e.GetPosition(_host);
            var w = Math.Max(1, _host.ActualWidth);
            var h = Math.Max(1, _host.ActualHeight);
            var dx = (p.X - _grabPoint.X) / w;
            var dy = (p.Y - _grabPoint.Y) / h;
            var minW = MinPxW / w;
            var minH = MinPxH / h;
            var r = _grabRect;

            if (_mode == "move")
            {
                Card.X = _host.SnapV(Math.Clamp(r.X + dx, 0, 1 - r.Width));
                Card.Y = _host.SnapV(Math.Clamp(r.Y + dy, 0, 1 - r.Height));
            }
            else
            {
                double x = r.X, y = r.Y, cw = r.Width, ch = r.Height;
                if (_mode.Contains('w'))
                {
                    var nx = _host.SnapV(Math.Clamp(r.X + dx, 0, r.Right - minW));
                    cw = r.Right - nx;
                    x = nx;
                }
                if (_mode.Contains('e'))
                    cw = Math.Clamp(_host.SnapV(r.X + r.Width + dx) - r.X, minW, 1 - r.X);
                if (_mode.Contains('n'))
                {
                    var ny = _host.SnapV(Math.Clamp(r.Y + dy, 0, r.Bottom - minH));
                    ch = r.Bottom - ny;
                    y = ny;
                }
                if (_mode.Contains('s'))
                    ch = Math.Clamp(_host.SnapV(r.Y + r.Height + dy) - r.Y, minH, 1 - r.Y);
                Card.X = x;
                Card.Y = y;
                Card.W = Math.Max(minW, cw);
                Card.H = Math.Max(minH, ch);
            }
            _host.InvalidateArrange();
            e.Handled = true;
        }

        private void OnDrop(object sender, MouseButtonEventArgs e)
        {
            if (_mode is null) return;
            _mode = null;
            ((UIElement)e.Source).ReleaseMouseCapture();
            _host.NotifyChanged();
            e.Handled = true;
        }

        protected override Size ArrangeOverride(Size final)
        {
            var s = base.ArrangeOverride(final);
            foreach (Border h in _handleLayer.Children)
            {
                var spec = Handles.First(x => x.Name == (string)h.Tag);
                Canvas.SetLeft(h, spec.Cx * final.Width - 5.5);
                Canvas.SetTop(h, spec.Cy * final.Height - 5.5);
            }
            return s;
        }
    }
}
