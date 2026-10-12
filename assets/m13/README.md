# Tianmao MagicBox M13 DTB

`meson-gxbb-tianmao-m13.dtb` 用于可选的 M13 boot profile。
平台为 Amlogic S905-B / Meson GXBB，1 GiB RAM，以太网使用 RMII / IP101GR。

DTB SHA-256：

```text
08ebca98b5049d95bcf270374d41f608edc19658392f3c1b35fcf904e8b6f927
```

相邻的 `.decompiled.dts` 是该二进制的反编译文本，用于检查节点和属性，
不是原始 DTS，也不保证能重建字节完全一致的二进制。
该 DTB 基于 P20x 板型描述和主线 Amlogic 设备树，沿用 GPL-2.0+ OR MIT 许可。

内核源码与构建参考：

- [ophub kernel sources](https://github.com/ophub/kernel#kernel-source-code)
- [Linux 6.12.y](https://github.com/unifreq/linux-6.12.y)
- [ophub kernel build tools](https://github.com/ophub/amlogic-s9xxx-armbian/tree/main/compile-kernel)

软件包保留内核配置和构建来源信息；这些链接不代表二进制已从某个指定源码
commit 独立重建。
