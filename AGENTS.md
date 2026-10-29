# 本地模型服务存储约定

- 用户要求：本地模型服务以后从 F 盘运行，减少 C 盘写入。
- 统一模型区为 `F:\Models`：`Ollama`、`HuggingFace`、`ModelScope`、`Speech\CosyVoice`。新模型优先下载到对应目录；原 C 盘模型路径通过目录联接保持兼容，不要在 C 盘重新创建实体模型目录。
- 本项目使用 `F:\LocalModelServices` 保存推理运行库；`F:\LocalModelServices\b-code` 保存工作目录、日志、PID、临时文件、缓存和实验记录。
- 通过 `b-code/start.ps1` 启动。项目源码可保留在 C 盘；不要把服务运行数据或新模型重新写入 C 盘。`b-code/runs` 应指向 F 盘记录目录。
- 切换或重启前检查实验状态，不中断正在进行的实验，除非用户明确要求停止。
- 以上约定仅适用于可配置的项目服务路径；不要声称控制了 Windows 页面文件、系统日志等系统级写入。
