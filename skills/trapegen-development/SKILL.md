---
name: trapegen-development
description: 遵守 TrapeGen 项目的环境和依赖规则，适用于安装包、运行代码或维护项目依赖时。
---

# TrapeGen 开发规则

1. 使用 `uv` 管理项目环境。安装任何包或运行代码前，在项目根目录执行 `source .venv/bin/activate` 激活生产环境，并在同一个 shell 中执行后续命令。
2. 将项目使用的所有第三方包记录在 `setup.py` 的依赖配置中。迁移到已激活的目标环境后，在项目根目录执行 `uv pip install -e .`，安装项目及其依赖。
