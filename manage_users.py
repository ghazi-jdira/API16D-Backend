"""
Manage calculator logins (writes users.json).

Usage:
  python manage_users.py add <username> <password>     # add or update a user
  python manage_users.py remove <username>             # delete a user
  python manage_users.py list                          # show usernames

Usernames are stored lowercase. Passwords are never stored in plaintext --
only their PBKDF2-HMAC-SHA256 hash is saved.
"""
import sys

from userauth import hash_password, load_users, save_users


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1

    cmd = argv[1].lower()
    users = load_users()

    if cmd == "add" and len(argv) == 4:
        username = argv[2].strip().lower()
        users[username] = hash_password(argv[3])
        save_users(users)
        print(f"Saved user '{username}'. Total users: {len(users)}")
        return 0

    if cmd == "remove" and len(argv) == 3:
        username = argv[2].strip().lower()
        if users.pop(username, None) is None:
            print(f"No such user '{username}'.")
            return 1
        save_users(users)
        print(f"Removed user '{username}'. Total users: {len(users)}")
        return 0

    if cmd == "list":
        if not users:
            print("(no users)")
        else:
            for u in sorted(users):
                print(u)
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
