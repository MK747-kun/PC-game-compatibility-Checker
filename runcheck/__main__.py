import sys
from .cli import main as cli_main

if len(sys.argv) == 1 or sys.argv[1] == "gui":
    from .gui import main
    main()
else:
    cli_main()
