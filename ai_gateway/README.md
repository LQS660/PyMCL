# PyMCL 公益 AI 网关

启动器**不带** NewAPI 令牌。把 `sk-` 只放在这台机器的环境变量里。

```bat
copy .env.example .env
:: 编辑 .env 填你的 NewAPI
python server.py
```

健康检查：`GET http://127.0.0.1:8787/health`  
对话口：`POST /pymcl/chat`（必须带请求头 `X-PyMCL-Client: PyMCL/x.y.z`）

打包给小白前，把启动器设置里的公益网关填成公网地址，或改 `mclauncher/ai/defaults.py` 的 `DEFAULT_GATEWAY_URL`。
