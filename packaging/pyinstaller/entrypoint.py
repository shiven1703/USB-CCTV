"""PyInstaller entrypoint that imports the installed package by its absolute name."""

from usb_cctv_recorder.__main__ import main


raise SystemExit(main())
