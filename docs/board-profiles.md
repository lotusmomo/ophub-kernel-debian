# 可选板级 profiles

通用构建不要求本仓库内的自定义板级 DTB，也不会自动安装任何板级 support 包。
上游 Amlogic DTB 始终随版本化内核包安装。

## Tianmao MagicBox M13

M13 profile 包含固定的 `meson-gxbb-tianmao-m13.dtb` 和
`/usr/share/u-boot-menu/conf.d/40-m13.conf`，用于为 M13 选择 DTB 和菜单默认值。
它不包含特定机器的 root UUID、NAS 地址或分区迁移脚本。

构建时显式启用：

```sh
PYTHONPATH=src python3 -m ophub_kernel.cli build \
    --output .cache/packages-m13-2 --revision 2 --with-m13-profile
```

或者：

```sh
OPHUB_WITH_M13_PROFILE=1 bash scripts/build-local.sh \
    2 /path/to/private-signing-home PUBLIC_FINGERPRINT
```

这会额外生成 `m13-boot-support`，并将固定 M13 DTB 放入同版本内核包。
profile 依赖同版本内核包和 `u-boot-menu`；管理员的 `/etc/u-boot-menu/conf.d/`
配置优先于它的默认值。M13 输入另行校验 F2FS、device-mapper 和 Meson MMC 支持。

M13 用户可显式安装：

```sh
sudo apt-get install linux-image-arm64 m13-boot-support
```

其他板型不要安装这个包。板级电源、MMC、PHY、音频和引导内存保留区应以
具体硬件对应的设备树为准。DTB 输入摘要和来源说明见
[M13 DTB](../assets/m13/README.md)。

revision 在整个仓库内唯一，不按 profile 分别计数；不同缓存目录不代表可以
复用同一个包版本。上面的 revision 2 也应替换为实际尚未使用的 revision。
已发布 profile 的仓库不能在后续更新中直接停用它，否则旧菜单可能引用缺失的
DTB；发布工具会拒绝这种切换。
