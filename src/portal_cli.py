"""create portal users without putting passwords in shell history: python src/portal_cli.py create-user <username> <analyst|lender> [LENDER_X]  (prompts for the password)"""
import sys, getpass, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from portal_store import Store
root = pathlib.Path(__file__).resolve().parent.parent
if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "create-user": sys.exit(__doc__)
    pw = getpass.getpass("Password (min 10 characters): "); Store(root / "outputs/portal").create_user(sys.argv[2], pw, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None); print("user saved")
