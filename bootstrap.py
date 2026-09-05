from app import init_db
from db_layer import database_backend

if __name__ == "__main__":
    init_db()
    print(f"RouteOps V0.3.0 database initialized ({database_backend()}).")
