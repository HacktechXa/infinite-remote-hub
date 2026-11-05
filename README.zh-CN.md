# Infinite Remote Hub · 型号适配库

[English version](README.md)

Infinite Remote 的独立遥控器适配库。首个型号是小米蓝牙遥控器 2 Pro。新型号使用 v2 包格式，包含中英文字、品牌图标、默认动作与行为声明；工具也接受旧版 v1 包。无需第三方 Python 包，要求 Python 3.10+。

GitHub 仓库为 `szhjia/infinite-remote-hub`。

## 使用与命令

```sh
python3 scripts/remote_hub.py validate
python3 scripts/remote_hub.py pack --output dist
python3 -m unittest discover -s tests -v
```

ZIP 内为单个型号文件夹，包含 manifest/layout/inputs JSON、正面 PNG、可选品牌 PNG 及说明。新安装的应用不内置真实型号，从资源库安装或直接导入 ZIP。同一来源只能用更高 release 更新型号；其他来源不能覆盖已安装型号。用户映射独立保存。`metadata.json` 为订阅源和官网提供中英设置步骤及限制。

## 显式同步

```sh
# 只比较，差异时退出码为 1；路径由调用者提供
python3 scripts/remote_hub.py sync-app --app /absolute/path/to/app
# 旧版资源复制工具；不要用于向正式应用重新内置型号
python3 scripts/remote_hub.py sync-app --app /absolute/path/to/app --write
# 导出完整订阅源：catalog.json、packages/、assets/
python3 scripts/remote_hub.py export-source --output /absolute/path/to/source
# 相同导出器可生成官网独立快照
python3 scripts/remote_hub.py export-web --output /absolute/path/to/website/public/hub
```

不要通过软链接、子模块或隐式相邻路径连接仓库。更新型号后先校验与测试，再显式同步并检查目标仓差异。打包固定顺序、时间和权限，相同内容产生相同 SHA256。引用的资源不允许软链接或路径穿越。导出仅写入明确目标，不发布、不创建远端。官方订阅地址为 `https://raw.githubusercontent.com/szhjia/infinite-remote-hub/main/catalog.json`；发布是独立授权操作：校验导出后，将 catalog.json、packages、assets 提交并推送到公开 hub 仓库，再检查公开目录与资源包哈希。本地导出完成不代表订阅已上线。具体协议见 [PROTOCOL.md](PROTOCOL.md)。

## 型号说明与来源

`models/xiaomi-2-pro/` 内有中文、英文说明及 `SOURCE.md`。[ADAPTING.md](ADAPTING.md) 描述新增型号流程，[HARDWARE-TEST-TEMPLATE.md](HARDWARE-TEST-TEMPLATE.md) 用于记录实体测试。

设备素材、来源记录和第三方资料保留其原有许可证与来源。本项目许可证不会替代或扩大这些权利。

## Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=szhjia/infinite-remote-hub&type=Date)](https://star-history.com/#szhjia/infinite-remote-hub&Date)

## 许可证

Copyright (C) 2026 Infinite Remote contributors.

本项目采用 [GNU 通用公共许可证第 3 版或（由你选择）任何更新版本](LICENSE)（`GPL-3.0-or-later`）。允许商业使用；对外分发本软件或衍生作品时，必须遵守 GPL 关于对应源码和相同授权的要求。
