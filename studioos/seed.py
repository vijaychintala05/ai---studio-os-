"""Optional fictional demo dataset. Never run on an existing live database."""
from .db import init_db,SessionLocal,Project
from .main import create_project,create_task,create_cost

def seed():
    init_db()
    with SessionLocal() as db:
        if db.query(Project).count():
            print('Existing projects detected. Refusing to seed into nonempty database.');return
        a=create_project(db,'Villa A','Demo client',500000000)
        b=create_project(db,'Apartment B','Demo client',1200000000)
        create_task(db,a.id,'Review ground floor working drawings','Architect')
        create_task(db,b.id,'Confirm foundation inspection','Site engineer')
        create_cost(db,a.id,'expense','Soil investigation','Demo geotech firm',850000)
        create_cost(db,a.id,'commitment','Flooring material purchase order','ABC Traders',12500000)
        print('Created two clearly fictional demonstration projects.')
if __name__=='__main__': seed()
