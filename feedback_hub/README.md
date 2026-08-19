# PyMCL 反馈中心

两个端口，互不混用：

| 端口 | 用途 | 穿透 |
| --- | --- | --- |
| `INGEST_PORT` 默认 18788 | 启动器上报 `POST /api/v1/feedback` `POST /api/v1/heartbeat` | 给用户用，穿透这个 |
| `UI_PORT` 默认 18789 | 开发者看板 WebUI | 只给你自己，另开一条或走 SSH |

```bat
python -m feedback_hub
```

上报口不提供网页。看板：http://127.0.0.1:18789

`ADMIN_TOKEN` 填了以后看板要带 `?token=`。

启动器 `DEFAULT_FEEDBACK_URL` 必须指向上报口，不要填看板端口。

第一次打开启动器会弹窗，用户手动点「同意」后才会上传。
