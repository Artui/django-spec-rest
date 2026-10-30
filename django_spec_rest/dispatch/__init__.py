"""The HTTP edge's call into the kernel's ``dispatch``.

``kernel_edge`` reads a view's request into the one argument dict the kernel
takes and dispatches a kernel spec; ``kernel_refusals`` answers the kernel's
refusals as DRF's. Import them by module: nothing here is a public name.
"""
