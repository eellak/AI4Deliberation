from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
import sys
from db_models import Ministry, Consultation, Article, Comment, Document

def count_empty_or_default(session, model, fields, defaults=None):
    if defaults is None:
        defaults = {}
    model_name = model.__tablename__
    results = {}
    total = session.query(model).count()
    results['total'] = total
    for field in fields:
        col = getattr(model, field)
        null_count = session.query(model).filter(col == None).count()
        empty_count = session.query(model).filter(col == '').count()
        default_count = 0
        if field in defaults:
            default_val = defaults[field]
            default_count = session.query(model).filter(col == default_val).count()
        results[field] = {
            'null': null_count,
            'empty': empty_count,
            'default': default_count,
            'populated': total - null_count - empty_count - default_count
        }
    return results

def main():
    # Use the database file in the project root directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, 'deliberation_data_gr.db')
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        sys.exit(1)
    
    print(f"Using database: {db_path}")
    
    # Use the absolute path for SQLAlchemy
    engine = create_engine(f'sqlite:///{db_path}')
    Session = sessionmaker(bind=engine)
    session = Session()
    
    schema = {
        Ministry: ['code', 'name', 'url'],
        Consultation: ['post_id', 'title', 'start_minister_message', 'end_minister_message', 'start_date', 'end_date', 'is_finished', 'url', 'total_comments', 'accepted_comments', 'ministry_id'],
        Article: ['post_id', 'title', 'content', 'url', 'consultation_id'],
        Comment: ['comment_id', 'username', 'date', 'content', 'article_id'],
        Document: ['title', 'url', 'type', 'consultation_id']
    }
    defaults = {
        'is_finished': False,
        'total_comments': 0,
        'accepted_comments': 0,
        'username': 'Anonymous',
        'comment_id': '',
        'content': '',
        'type': 'unknown',
        'title': '',
        'url': '',
    }
    
    grand_results = {}
    for model, fields in schema.items():
        try:
            grand_results[model.__tablename__] = count_empty_or_default(session, model, fields, defaults)
            print(f"Analyzed table: {model.__tablename__}")
        except Exception as e:
            print(f"Error analyzing {model.__tablename__}: {str(e)}")
    
    # Print results
    print('\n=== Field Population Report ===')
    total_entities = 0
    total_attributes = 0
    populated_attributes = 0
    for model, fields in schema.items():
        model_name = model.__tablename__
        if model_name not in grand_results:
            continue
            
        entity_count = grand_results[model_name]['total']
        total_entities += entity_count
        for field in fields:
            total_attributes += entity_count
            populated = grand_results[model_name][field]['populated']
            populated_attributes += populated
            print(f"{model_name}.{field}: {populated}/{entity_count} populated")
    
    print(f'\nTotal entities: {total_entities}')
    print(f'Total attributes: {total_attributes}')
    print(f'Populated attributes: {populated_attributes}')
    if total_attributes > 0:
        print(f'Population rate: {populated_attributes/total_attributes*100:.1f}%')
    else:
        print('Population rate: N/A')
    
    print('\nDetailed field stats:')
    import pprint
    pprint.pprint(grand_results)

if __name__ == "__main__":
    main()
