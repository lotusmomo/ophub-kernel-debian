# 回退到 Debian 官方内核

安装 ophub 内核前，保留至少一个已验证的 Debian 版本化内核包，并把它
标为手工安装。备份启动菜单、设备树、根分区配置及自定义 initramfs 脚本。
首次切换时为启动菜单保留等待时间，并准备串口或可用的恢复介质。

如果新内核无法启动，从现有 U-Boot/extlinux 菜单选择原有 Debian 内核。
本项目不改变启动固件或分区布局，回退无需重写引导区。

本项目的 `linux-image-arm64` 使用 epoch `1:`，仅停用自定义 APT 源不会
自动切回 Debian 官方元包。需要检查官方源提供的版本并显式降级：

```sh
apt-cache policy linux-image-arm64
sudo apt-get install --allow-downgrades 'linux-image-arm64=<DEBIAN_VERSION>'
```

把 `<DEBIAN_VERSION>` 替换为实际的官方元包版本。降级前检查 APT 模拟结果，
确认不会删除运行中的内核或恢复内核。不要把 `autoremove` 作为恢复步骤。

对于 U-Boot/extlinux 系统，运行 `u-boot-update` 并检查菜单中的内核、
initramfs、DTB 和 root 参数，再重启选择 Debian 内核。成功回到旧内核后，
如不再需要板级 profile，可显式卸载相应 support 包；管理员配置不会被 profile
默认值覆盖。没有旧内核或启动文件损坏时，先从恢复介质修复启动配置。
