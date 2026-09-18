using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>
/// 启动页布局文档，与 mclauncher/ui_layout.py 的 LayoutItem / LayoutDoc 同一个形状：
/// {version, grid, items:[{id,type,x,y,w,h,z,hidden,settings}]}。几何是 0~1 的画布比例，
/// grid 是吸附步长（像素，0 = 自由）。Qt / 网页版 / WPF 读写的是桥上同一份
/// （get_layout / save_layout / *_layout_profile），在哪边拖好另一边打开就是同一个。
/// </summary>
public sealed class DashCard
{
    public string Id { get; set; } = "";
    public string Type { get; set; } = "";
    public double X { get; set; }
    public double Y { get; set; }
    public double W { get; set; } = 0.3;
    public double H { get; set; } = 0.3;
    public int Z { get; set; }
    public bool Hidden { get; set; }
    /// <summary>卡片自己的设置（快捷入口选了哪些之类），WPF 原样带着不解释。</summary>
    public JsonElement? Settings { get; set; }

    public DashCard Clone() => new()
    {
        Id = Id, Type = Type, X = X, Y = Y, W = W, H = H, Z = Z, Hidden = Hidden,
        Settings = Settings is { } s ? s.Clone() : null,
    };

    public static DashCard FromJson(JsonElement e)
    {
        var card = new DashCard
        {
            Id = Str(e, "id"),
            Type = Str(e, "type") is { Length: > 0 } t ? t : "notes",
            X = Clamp01(Num(e, "x", 0)),
            Y = Clamp01(Num(e, "y", 0)),
            W = Math.Clamp(Num(e, "w", 0.3), 0.04, 1),
            H = Math.Clamp(Num(e, "h", 0.3), 0.04, 1),
            Z = (int)Num(e, "z", 0),
            Hidden = e.TryGetProperty("hidden", out var h) && h.ValueKind == JsonValueKind.True,
        };
        if (e.TryGetProperty("settings", out var s) && s.ValueKind == JsonValueKind.Object) card.Settings = s.Clone();
        return card;
    }

    public Dictionary<string, object?> ToDict() => new()
    {
        ["id"] = Id, ["type"] = Type,
        ["x"] = Math.Round(X, 5), ["y"] = Math.Round(Y, 5),
        ["w"] = Math.Round(W, 5), ["h"] = Math.Round(H, 5),
        ["z"] = Z, ["hidden"] = Hidden,
        ["settings"] = Settings is { } s ? s : new Dictionary<string, object?>(),
    };

    private static string Str(JsonElement e, string k) =>
        e.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

    private static double Num(JsonElement e, string k, double fallback)
    {
        if (!e.TryGetProperty(k, out var v)) return fallback;
        if (v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var d)) return d;
        if (v.ValueKind == JsonValueKind.String && double.TryParse(v.GetString(), out var p)) return p;
        return fallback;
    }

    private static double Clamp01(double v) => Math.Clamp(v, 0, 1);
}

public sealed class DashLayout
{
    public const int Version = 1;
    /// <summary>与 Qt GRID_CHOICES 一致：0 自由，其余是像素步长。</summary>
    public static readonly int[] GridChoices = { 0, 4, 8, 16, 24 };

    public int Grid { get; set; } = 8;
    public List<DashCard> Items { get; set; } = new();

    public bool Snap => Grid > 0;

    public DashLayout Clone() => new() { Grid = Grid, Items = Items.Select(c => c.Clone()).ToList() };

    public IEnumerable<DashCard> VisibleItems() => Items.Where(c => !c.Hidden).OrderBy(c => c.Z);

    public int NextZ() => Items.Count == 0 ? 0 : Items.Max(c => c.Z) + 1;

    /// <summary>修 id 重复 / z 序空洞；每次落盘前调一次，对齐 LayoutDoc.normalize。</summary>
    public void Normalize()
    {
        var seen = new HashSet<string>();
        for (var i = 0; i < Items.Count; i++)
        {
            var it = Items[i];
            var baseId = it.Id is { Length: > 0 } ? it.Id : $"{it.Type}-{i}";
            var nid = baseId;
            var n = 2;
            while (!seen.Add(nid)) nid = $"{baseId}-{n++}";
            it.Id = nid;
        }
        var z = 0;
        foreach (var it in Items.OrderBy(c => c.Z).ToList()) it.Z = z++;
    }

    public Dictionary<string, object?> ToDict()
    {
        Normalize();
        return new Dictionary<string, object?>
        {
            ["version"] = Version,
            ["grid"] = Grid,
            ["items"] = Items.Select(c => c.ToDict()).ToList(),
        };
    }

    public string ToJson() => JsonSerializer.Serialize(ToDict(), new JsonSerializerOptions
    {
        WriteIndented = true,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    });

    /// <summary>宽松解析（对齐 LayoutDoc.from_dict）：不是文档就回内置默认；显式空列表照留。</summary>
    public static DashLayout FromJson(JsonElement e)
    {
        if (e.ValueKind != JsonValueKind.Object) return Default();
        var grid = 8;
        if (e.TryGetProperty("grid", out var g))
        {
            if (g.ValueKind == JsonValueKind.Number && g.TryGetInt32(out var n)) grid = n;
            else if (g.ValueKind == JsonValueKind.String && int.TryParse(g.GetString(), out var m)) grid = m;
        }
        var doc = new DashLayout { Grid = Math.Max(0, grid) };
        var hasList = e.TryGetProperty("items", out var items) && items.ValueKind == JsonValueKind.Array;
        if (hasList)
        {
            foreach (var row in items.EnumerateArray())
                if (row.ValueKind == JsonValueKind.Object) doc.Items.Add(DashCard.FromJson(row));
        }
        if (doc.Items.Count == 0 && !hasList) return Default();
        doc.Normalize();
        return doc;
    }

    /// <summary>严格解析（对齐 parse_doc）：结构不对返回 null，未知卡片类型丢弃。</summary>
    public static DashLayout? Parse(JsonElement e, IReadOnlyCollection<string> knownTypes)
    {
        if (e.ValueKind != JsonValueKind.Object) return null;
        if (!e.TryGetProperty("items", out var items) || items.ValueKind != JsonValueKind.Array || items.GetArrayLength() == 0)
            return null;
        var doc = FromJson(e);
        doc.Items = doc.Items.Where(c => knownTypes.Contains(c.Type)).ToList();
        return doc.Items.Count > 0 ? doc : null;
    }

    /// <summary>内置默认（对齐 ui_layout.default_doc）：横幅通栏 + 左侧启动配置。桥连不上时兜底用。</summary>
    public static DashLayout Default() => new()
    {
        Grid = 8,
        Items = new List<DashCard>
        {
            new() { Id = "banner-main", Type = "banner", X = 0, Y = 0, W = 1, H = 0.30, Z = 0 },
            new() { Id = "config-main", Type = "config", X = 0, Y = 0.315, W = 0.315, H = 0.685, Z = 1 },
        },
    };
}

/// <summary>get_layout 回来的整份：当前文档 + 方案表 + 内置默认 + 各卡片最小尺寸。</summary>
public sealed class LayoutState
{
    public DashLayout Doc { get; set; } = DashLayout.Default();
    public string Profile { get; set; } = "";
    public List<string> Profiles { get; set; } = new();
    public DashLayout Default { get; set; } = DashLayout.Default();
    public Dictionary<string, (int W, int H)> MinSizes { get; set; } = new();

    public static LayoutState FromJson(JsonElement e)
    {
        var st = new LayoutState();
        if (e.ValueKind != JsonValueKind.Object) return st;
        if (e.TryGetProperty("doc", out var doc)) st.Doc = DashLayout.FromJson(doc);
        if (e.TryGetProperty("profile", out var p) && p.ValueKind == JsonValueKind.String) st.Profile = p.GetString() ?? "";
        if (e.TryGetProperty("profiles", out var ps) && ps.ValueKind == JsonValueKind.Array)
            st.Profiles = ps.EnumerateArray().Where(x => x.ValueKind == JsonValueKind.String)
                .Select(x => x.GetString() ?? "").Where(s => s.Length > 0).ToList();
        if (e.TryGetProperty("default", out var d)) st.Default = DashLayout.FromJson(d);
        if (e.TryGetProperty("min_sizes", out var ms) && ms.ValueKind == JsonValueKind.Object)
        {
            foreach (var kv in ms.EnumerateObject())
            {
                if (kv.Value.ValueKind != JsonValueKind.Array || kv.Value.GetArrayLength() < 2) continue;
                if (kv.Value[0].TryGetInt32(out var w) && kv.Value[1].TryGetInt32(out var h)) st.MinSizes[kv.Name] = (w, h);
            }
        }
        return st;
    }
}

/// <summary>
/// 自由画布。卡片坐标是 0~1 归一化的，窗口怎么缩放都按比例走；
/// 编辑态下可拖动、八向缩放、按像素网格吸附。
/// </summary>
public sealed class DashHost : Panel
{
    private const double Gap = 10;
    private static readonly (int W, int H) FallbackMin = (200, 120);

    private readonly Dictionary<string, FrameworkElement> _contents = new();
    private readonly List<CardView> _views = new();
    private readonly Border _gridLayer = new();
    private DashLayout _layout = DashLayout.Default();
    private bool _edit;

    public event Action? Changed;
    public Func<string, UIElement?>? ContentFactory;
    public Func<string, string>? TitleFactory;
    /// <summary>各卡片类型最小像素尺寸；桥连上后用 get_layout 的 min_sizes 覆盖。</summary>
    public Dictionary<string, (int W, int H)> MinSizes { get; set; } = new();

    public DashLayout Layout => _layout;

    public bool EditMode
    {
        get => _edit;
        set
        {
            if (_edit == value) return;
            _edit = value;
            foreach (var v in _views) v.SetEdit(value);
            RefreshGridLayer();
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
        foreach (var card in _layout.VisibleItems())
        {
            var content = Cached(card.Type);
            // 别的前端才会画的卡片类型（比如网页版的皮肤卡）留在文档里但不画，导出时不丢
            if (content is null) continue;
            var view = new CardView(this, card);
            view.SetContent(TitleFactory?.Invoke(card.Type) ?? card.Type, content);
            view.SetEdit(_edit);
            _views.Add(view);
            Children.Add(view);
        }
        RefreshGridLayer();
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
        if (_layout.Items.Any(c => c.Type == type && !c.Hidden)) return;
        var hidden = _layout.Items.FirstOrDefault(c => c.Type == type && c.Hidden);
        if (hidden != null)
        {
            hidden.Hidden = false;
            hidden.Z = _layout.NextZ();
        }
        else
        {
            var (x, y, w, h) = FindFreeSpot(type);
            _layout.Items.Add(new DashCard { Type = type, X = x, Y = y, W = w, H = h, Z = _layout.NextZ() });
        }
        _layout.Normalize();
        Rebuild();
        Changed?.Invoke();
    }

    /// <summary>新卡片落在最空的那一角：先试四个角，都被占了就叠在左上角偏一点。</summary>
    private (double X, double Y, double W, double H) FindFreeSpot(string type)
    {
        var hostW = Math.Max(1, ActualWidth);
        var hostH = Math.Max(1, ActualHeight);
        var (minW, minH) = MinSizes.GetValueOrDefault(type, FallbackMin);
        var w = Math.Clamp(Math.Max(0.3, minW / hostW), 0.1, 1);
        var h = Math.Clamp(Math.Max(0.3, minH / hostH), 0.1, 1);
        foreach (var (x, y) in new[] { (0.0, 0.0), (1 - w, 0.0), (0.0, 1 - h), (1 - w, 1 - h) })
        {
            var rect = new Rect(x, y, w, h);
            if (!_layout.VisibleItems().Any(c => rect.IntersectsWith(new Rect(c.X, c.Y, c.W, c.H))))
                return (x, y, w, h);
        }
        return (0.05, 0.05, w, h);
    }

    public void RemoveCard(DashCard card)
    {
        _layout.Items.Remove(card);
        Rebuild();
        Changed?.Invoke();
    }

    public bool Has(string type) => _layout.Items.Any(c => c.Type == type && !c.Hidden);

    public void NotifyChanged() => Changed?.Invoke();

    public (double W, double H) MinPx(string type)
    {
        var (w, h) = MinSizes.GetValueOrDefault(type, FallbackMin);
        return (w, h);
    }

    private void RefreshGridLayer()
    {
        var show = _edit && _layout.Snap;
        _gridLayer.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
        if (!show)
        {
            _gridLayer.Background = null;
            return;
        }
        var step = _layout.Grid;
        _gridLayer.Background = new DrawingBrush
        {
            TileMode = TileMode.Tile,
            Viewport = new Rect(0, 0, step, step),
            ViewportUnits = BrushMappingMode.Absolute,
            Drawing = new GeometryDrawing
            {
                Geometry = new RectangleGeometry(new Rect(0, 0, step, step)),
                Pen = new Pen(new SolidColorBrush(Color.FromArgb(38, 46, 155, 107)), 0.6),
            },
            Opacity = 0.9,
        };
    }

    /// <summary>把一个比例坐标按像素网格吸附（对齐 Qt DashboardCard._snap：拖拽在像素空间，落点换回比例）。</summary>
    public double SnapV(double v, double axisPx)
    {
        v = Math.Clamp(v, 0, 1);
        if (!_layout.Snap || axisPx <= 1) return v;
        var px = Math.Round(v * axisPx / _layout.Grid) * _layout.Grid;
        return Math.Clamp(px / axisPx, 0, 1);
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
        v.Card.Z = _layout.NextZ();
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

            _close = Ui.IconBtn(Ico.Close, L("移除卡片"), (_, _) => _host.RemoveCard(Card), 11);
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
            var (minPxW, minPxH) = _host.MinPx(Card.Type);
            var minW = Math.Min(1, (minPxW + Gap) / w);
            var minH = Math.Min(1, (minPxH + Gap) / h);
            var r = _grabRect;

            if (_mode == "move")
            {
                Card.X = _host.SnapV(Math.Clamp(r.X + dx, 0, 1 - r.Width), w);
                Card.Y = _host.SnapV(Math.Clamp(r.Y + dy, 0, 1 - r.Height), h);
            }
            else
            {
                double x = r.X, y = r.Y, cw = r.Width, ch = r.Height;
                if (_mode.Contains('w'))
                {
                    var nx = _host.SnapV(Math.Clamp(r.X + dx, 0, r.Right - minW), w);
                    cw = r.Right - nx;
                    x = nx;
                }
                if (_mode.Contains('e'))
                    cw = Math.Clamp(_host.SnapV(r.X + r.Width + dx, w) - r.X, minW, 1 - r.X);
                if (_mode.Contains('n'))
                {
                    var ny = _host.SnapV(Math.Clamp(r.Y + dy, 0, r.Bottom - minH), h);
                    ch = r.Bottom - ny;
                    y = ny;
                }
                if (_mode.Contains('s'))
                    ch = Math.Clamp(_host.SnapV(r.Y + r.Height + dy, h) - r.Y, minH, 1 - r.Y);
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
