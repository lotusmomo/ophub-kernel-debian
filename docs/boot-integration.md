# Debian 启动集成

软件包保留 ophub 的 kernel release，例如 `6.12.112-ophub`，并安装到：

- `/boot/vmlinuz-<release>`
- `/boot/config-<release>` 和 `/boot/System.map-<release>`
- `/usr/lib/modules/<release>/`
- `/usr/lib/linux-image-<release>/amlogic/`
- `/boot/dtbs/<release>/amlogic/`

Debian `initramfs-tools` 在目标系统生成 `/boot/initrd.img-<release>`。
上游预制 initramfs 不随包安装，因此目标系统的存储驱动、根文件系统模块和
自定义启动脚本可以进入本机生成的 initramfs。

## U-Boot / extlinux

使用自己设备对应的 DTB，不要照抄其他型号的配置。`u-boot-menu` 的管理员
配置通常位于 `/etc/u-boot-menu/conf.d/`，优先于软件包提供的默认值。
例如，版本化 DTB 的目录设置为：

```sh
U_BOOT_FDT="amlogic/<BOARD>.dtb"
U_BOOT_FDT_DIR="/boot/dtbs/"
U_BOOT_SYNC_DTBS="false"
```

先将 `<BOARD>.dtb` 替换为已验证的板型文件，并保留现有 root UUID、console、
blkdevparts 及其他必要参数。特殊 EPT / device-mapper 根分区的建立脚本仍由
管理员提供；通用包不推测或重写磁盘布局。

安装前后检查 `u-boot-update` 生成的 `/boot/extlinux/extlinux.conf`，确保每个
启动入口都有正确的 kernel、initrd、DTB 和 APPEND，且旧 Debian 入口仍可使用。
通用包不保存 U-Boot 环境，也不改变固件默认 bootcmd。

## flash-kernel

维护脚本会执行目标系统已有的 Debian 内核钩子，不能忽略不适用于自己设备的
`flash-kernel` 配置。设备依赖 flash-kernel 时，应配置受支持的 machine 和正确
的启动路径。若已验证设备使用自己的 U-Boot/extlinux 路径且不需要 flash-kernel，
可在安装前通过 flash-kernel 支持的 `machine=none` 设置禁用该处理流程。
软件包不会自动替设备作出这个选择，也不删除其维护钩子。

内核配置只有在 initramfs 及关键钩子成功后才会更新默认链接和 U-Boot 菜单。
如果配置失败，先修复报错，再运行 `dpkg --configure -a`；不要带着缺失启动文件重启。
