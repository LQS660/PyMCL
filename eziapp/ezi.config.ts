import { defineConfig } from "@eziapp-org/bridge";

export default defineConfig({
  application: {
    name: "PyMCL EziApp",
    package: "dev.pymcl.launcher",
    version: "1.0.0",
    description: "Minecraft 全版本启动器",
    author: "PyMCL",
    singleInstance: true,
    buildEntry: "dist"
  },
  window: {
    title: "PyMCL 启动器",
    size: { width: 1320, height: 840 },
    minSize: { width: 980, height: 650 },
    position: "remembered",
    backgroundMode: "mica",
    theme: "system",
    accentColor: "#2e9b6b",
    resizable: true,
    minimizable: true,
    maximizable: true
  }
});