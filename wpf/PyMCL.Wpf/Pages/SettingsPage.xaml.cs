using System.Windows.Controls;
using PyMCL.Services;

namespace PyMCL.Pages;

public partial class SettingsPage : UserControl
{
    public SettingsPage()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            var host = AppServices.Host;
            Info.Text = host == null
                ? "未连接"
                : $"根目录: {host.Root}\n桥端口: {host.Port}\nUI: WPF（PCL 同款方案，framework-dependent）\n后端: C bridge / Python fallback";
        };
    }
}
