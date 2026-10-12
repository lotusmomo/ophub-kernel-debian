# Debian package contract

The image package owns one kernel release, modules and versioned DTBs. It does
not ship an initramfs; Debian's native hooks generate it on the target. Failed
hooks fail package configuration. Tests execute the actual postinst in a
restricted chroot, including hook failure and repeated configuration.

The meta package alone uses epoch 1. To return to Debian, inspect
`apt-cache policy linux-image-arm64`, explicitly install the official version
with `--allow-downgrades`, then regenerate the boot menu. Keep the previous
versioned image installed until the replacement has booted successfully.

No package removes other image packages, rewrites disk partitioning, saves a
bootloader environment, flashes firmware or changes permanent eMMC settings.
Administrator configuration in `/etc/u-boot-menu/conf.d/` wins over packaged
defaults in `/usr/share/u-boot-menu/conf.d/`.
