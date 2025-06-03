import sqlalchemy
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, func
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

# Define the models (simplified for query, assuming they match the actual db_models.py structure)
class Ministry(Base):
    __tablename__ = 'ministries'
    id = Column(Integer, primary_key=True)
    code = Column(String(100), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False)
    consultations = sqlalchemy.orm.relationship("Consultation", back_populates="ministry")

class Consultation(Base):
    __tablename__ = 'consultations'
    id = Column(Integer, primary_key=True)
    post_id = Column(String(50), nullable=False)
    title = Column(String(500), nullable=False)
    start_minister_message = Column(Text)
    end_minister_message = Column(Text)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    is_finished = Column(Boolean, nullable=True)
    url = Column(String(255), nullable=False, unique=True)
    total_comments = Column(Integer, default=0)
    accepted_comments = Column(Integer, nullable=True)
    ministry_id = Column(Integer, ForeignKey('ministries.id'))
    ministry = sqlalchemy.orm.relationship("Ministry", back_populates="consultations")
    articles = sqlalchemy.orm.relationship("Article", back_populates="consultation")
    documents = sqlalchemy.orm.relationship("Document", back_populates="consultation")


class Article(Base):
    __tablename__ = 'articles'
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    content = Column(Text, nullable=True)
    raw_html = Column(Text, nullable=True)
    content_cleaned = Column(Text, nullable=True)
    extraction_method = Column(String(100), nullable=True)
    badness_score = Column(Float, nullable=True)
    greek_percentage = Column(Float, nullable=True)
    english_percentage = Column(Float, nullable=True)
    consultation_id = Column(Integer, ForeignKey('consultations.id'), nullable=False, index=True)
    consultation = sqlalchemy.orm.relationship("Consultation", back_populates="articles")
    comments = sqlalchemy.orm.relationship("Comment", back_populates="article", cascade="all, delete-orphan")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Comment(Base):
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True)
    comment_id = Column(String(50))
    username = Column(String(255), nullable=False)
    date = Column(DateTime)
    content = Column(Text, nullable=False)
    extraction_method = Column(String(100))
    article_id = Column(Integer, ForeignKey('articles.id'))
    article = sqlalchemy.orm.relationship("Article", back_populates="comments")

class Document(Base): # Added Document model as it's related to Consultation
    __tablename__ = 'documents'
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    file_path = Column(String(512), nullable=True)
    status = Column(String(50), nullable=True, default='pending', index=True)
    type = Column(String(100))
    content_type = Column(String(100), nullable=True)
    content = Column(Text, nullable=True)
    processed_text = Column(Text, nullable=True)
    extraction_method = Column(String(100), nullable=True)
    content_cleaned = Column(Text, nullable=True)
    badness_score = Column(Float, nullable=True)
    greek_percentage = Column(Float, nullable=True)
    english_percentage = Column(Float, nullable=True)
    consultation_id = Column(Integer, ForeignKey('consultations.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    consultation = sqlalchemy.orm.relationship("Consultation", back_populates="documents")


DATABASE_URL = "sqlite:///deliberation_data_gr_MIGRATED_FRESH_20250602170747.db" # Point to the latest migrated DB
URL_TO_FIND = "https://www.opengov.gr/yyka/?p=5399"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

db_session = SessionLocal()

try:
    # Try finding by exact URL first
    print(f"Searching for URL: {URL_TO_FIND}")
    consultation = db_session.query(Consultation).filter(Consultation.url == URL_TO_FIND).first()

    if not consultation:
        # Fallback to previous broader search if exact URL not found
        PID_TO_FIND = "5399" # Keep PID for fallback
        print(f"Exact URL not found. Trying by URL pattern %p={PID_TO_FIND}%...")
        consultation = db_session.query(Consultation).filter(Consultation.url.like(f'%p={PID_TO_FIND}%')).first()

        if not consultation:
            print(f"Consultation with p={PID_TO_FIND} in URL not found. Trying by post_id...")
            consultation = db_session.query(Consultation).filter(Consultation.post_id == PID_TO_FIND).first()

        if not consultation:
            print(f"Consultation with post_id={PID_TO_FIND} not found. Trying broader search in title and URL for '{PID_TO_FIND}'...")
            consultation = db_session.query(Consultation).filter(
                sqlalchemy.or_(
                    Consultation.url.contains(PID_TO_FIND),
                    Consultation.title.contains(PID_TO_FIND)
                )
            ).first()

    if consultation:
        print(f"Consultation Found: {consultation.title}")
        print(f"URL: {consultation.url}")
        print("\\nArticles:")
        if consultation.articles:
            for article in consultation.articles:
                comment_count = db_session.query(func.count(Comment.id)).filter(Comment.article_id == article.id).scalar()
                print(f"  - Title: {article.title}")
                print(f"    Comments: {comment_count}")
        else:
            print("  No articles found for this consultation.")
    else:
        print(f"No consultation found related to URL '{URL_TO_FIND}' or PID '5399'.")

finally:
    db_session.close() 