using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

public sealed partial class DownloadHubPage : UserControl
{
    private readonly VersionPage _version = new();
    private readonly CatalogPage _mod = new(CatalogKind.Mod);
    private readonly CatalogPage _pack = new(CatalogKind.Modpack);
    private readonly CatalogPage _data = new(CatalogKind.Datapack);
    private readonly CatalogPage _res = new(CatalogKind.ResourcePack);
    private readonly CatalogPage _shader = new(CatalogKind.Shader);
    private readonly JavaPage _java = new();
    private readonly Dictionary<string, FrameworkElement> _pages = new();
    private string _current = "原版游戏";
    private bool _lock;
    private int _tabGen;

    public DownloadHubPage()
    {
        InitializeComponent();
        _pages["原版游戏"] = _version;
        _pages["Mod"] = _mod;
        _pages["整合包"] = _pack;
        _pages["数据包"] = _data;
        _pages["资源包"] = _res;
        _pages["光影包"] = _shader;
        _pages["Java"] = _java;
        ShowCategory("原版游戏");
    }

    private void CatBar_Changed(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        if (_lock) return;
        if (sender.SelectedItem?.Tag is string title)
            ShowCategory(title);
    }

    public async void ShowCategory(string title)
    {
        if (!_pages.TryGetValue(title, out var page)) return;
        _current = title;
        foreach (var item in CatBar.Items)
        {
            if (item.Tag as string == title && CatBar.SelectedItem != item)
            {
                _lock = true;
                CatBar.SelectedItem = item;
                _lock = false;
            }
        }
        if (ReferenceEquals(Inner.Content, page) && page.Opacity >= 0.99)
        {
            ReloadCurrent();
            return;
        }
        var gen = ++_tabGen;
        Inner.ContentTransitions.Clear();
        if (Inner.Content is UIElement old && !ReferenceEquals(old, page))
            await Motion.TabOutAsync(old);
        if (gen != _tabGen) return;
        Inner.Content = page;
        await Motion.TabInAsync(page);
        ReloadCurrent();
    }

    public void ReloadCurrent()
    {
        if (_current == "原版游戏") _ = _version.ReloadAsync();
        else if (_current == "Java") _ = _java.ReloadAsync(false);
        else if (Inner.Content is CatalogPage cat) cat.ReloadInstances();
    }
}
