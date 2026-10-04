"""Cadastro manual de usuários (o TCC prevê que não há cadastro livre).

Uso: uv run python -m app.cli create-user "Nome" email@exemplo.com senha OPERADOR
"""

import argparse

from app.core.database import Base, SessionLocal, engine
from app.services.auth_service import ROLE_PERMISSIONS, AuthenticationService, seed_roles


def main() -> None:
    parser = argparse.ArgumentParser(prog="dockseal")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="Cria um usuário")
    create.add_argument("name")
    create.add_argument("email")
    create.add_argument("password")
    create.add_argument("role", choices=list(ROLE_PERMISSIONS))
    args = parser.parse_args()

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_roles(db)
        user = AuthenticationService(db).create_user(args.name, args.email, args.password, args.role)
        print(f"Usuário criado: {user.email} ({args.role})")


if __name__ == "__main__":
    main()
