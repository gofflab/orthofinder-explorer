from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from .models import Base, Orthogroup, Gene, Sequence, Species, GeneKeyLookup, IngestRun
import os

db = SQLAlchemy()

def create_app():
    """Create and configure the Flask application instance.

    Reads the database path from ORTHOFINDER_DB_PATH when set; otherwise uses
    the default SQLite file in the instance directory. Initializes SQLAlchemy
    and registers routes after ensuring tables exist.
    """
    app = Flask(__name__, instance_relative_config=True)
    db_path = os.environ.get('ORTHOFINDER_DB_PATH')
    if db_path:
        db_path = os.path.expanduser(db_path)
        if not os.path.isabs(db_path):
            db_path = os.path.join(app.instance_path, db_path)
    else:
        db_path = os.path.join(app.instance_path, 'orthofinder_new.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    species_colors_path = os.environ.get('ORTHOFINDER_SPECIES_COLORS_PATH')
    if species_colors_path:
        species_colors_path = os.path.expanduser(species_colors_path)
        if not os.path.isabs(species_colors_path):
            species_colors_path = os.path.join(app.root_path, species_colors_path)
    else:
        species_colors_path = os.path.join(app.root_path, 'static', 'species_colors.json')
    app.config['SPECIES_COLORS_PATH'] = species_colors_path

    db.init_app(app)

    with app.app_context():
        # Ensure tables are created
        from sqlalchemy import create_engine
        engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
        Base.metadata.create_all(engine)

        #print("App and DB initialized")
        from .routes import register_routes
        register_routes(app)
        
        # Unomment to see all routes
        #for rule in app.url_map.iter_rules():
        #    print(rule)
    return app
