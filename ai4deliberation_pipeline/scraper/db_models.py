#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, create_engine, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime

Base = declarative_base()

class Ministry(Base):
    """Ministry model - parent of consultations"""
    __tablename__ = 'ministries'
    
    id = Column(Integer, primary_key=True)
    code = Column(String(100), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False)
    
    # Relationships
    consultations = relationship("Consultation", back_populates="ministry")
    
    def __repr__(self):
        return f"<Ministry(code='{self.code}', name='{self.name}')>"

class Consultation(Base):
    """Consultation/legislation model - parent of articles and documents"""
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
    
    # Relationships
    ministry = relationship("Ministry", back_populates="consultations")
    articles = relationship("Article", back_populates="consultation")
    documents = relationship("Document", back_populates="consultation")
    
    def __repr__(self):
        return f"<Consultation(post_id='{self.post_id}', title='{self.title[:50]}...')>"

class Article(Base):
    """Article model with content and extraction metadata"""
    __tablename__ = 'articles'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    content = Column(Text, nullable=True)  # Markdownified content
    raw_html = Column(Text, nullable=True) # Raw HTML content, can be large
    # New fields for cleaned content and analysis
    content_cleaned = Column(Text, nullable=True)
    extraction_method = Column(String(100), nullable=True) # Method used for content extraction
    badness_score = Column(Float, nullable=True)
    greek_percentage = Column(Float, nullable=True)
    english_percentage = Column(Float, nullable=True)
    # Relationships
    consultation_id = Column(Integer, ForeignKey('consultations.id'), nullable=False, index=True)
    consultation = relationship("Consultation", back_populates="articles")
    comments = relationship("Comment", back_populates="article", cascade="all, delete-orphan")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Article(id={self.id}, title='{self.title[:50]}...', consultation_id={self.consultation_id})>"

class Comment(Base):
    """Comment model"""
    __tablename__ = 'comments'
    
    id = Column(Integer, primary_key=True)
    comment_id = Column(String(50))
    username = Column(String(255), nullable=False)
    date = Column(DateTime)
    content = Column(Text, nullable=False)
    extraction_method = Column(String(100))  # Method used for content extraction
    article_id = Column(Integer, ForeignKey('articles.id'))
    
    # Relationships
    article = relationship("Article", back_populates="comments")
    
    def __repr__(self):
        return f"<Comment(id={self.id}, username='{self.username}', date='{self.date}')>"

class Document(Base):
    """Document model with content and extraction quality fields"""
    __tablename__ = 'documents'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    file_path = Column(String(512), nullable=True) # Path to the downloaded file
    status = Column(String(50), nullable=True, default='pending', index=True) # e.g., pending, downloaded, processed, processing_failed, download_failed, processed_text_extraction_skipped
    type = Column(String(100))  # law_draft, analysis, deliberation_report, or other
    content_type = Column(String(100), nullable=True) # MIME type of the document e.g. application/pdf
    content = Column(Text, nullable=True) # Content from old DB (raw text if available, often from docling)
    processed_text = Column(Text, nullable=True) # Text extracted by current pipeline (e.g. from PDF via GlossAPI/Docling)
    extraction_method = Column(String(100), nullable=True) # Method used for processed_text extraction e.g. 'docling_glossapi', 'docling_tika'
    content_cleaned = Column(Text, nullable=True) # Cleaned content by Rust processor
    badness_score = Column(Float, nullable=True)   # Rust cleaner badness score (0-1)
    
    greek_percentage = Column(Float, nullable=True)  # Percentage of Greek content (numeric)
    english_percentage = Column(Float, nullable=True)  # Percentage of English content (numeric)
    
    # extraction_quality = Column(String(50), nullable=True)  # Legacy field - can be removed if not used
    
    consultation_id = Column(Integer, ForeignKey('consultations.id'))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    
    # Relationships
    consultation = relationship("Consultation", back_populates="documents")
    
    def __repr__(self):
        return f"<Document(title='{self.title}', type='{self.type}')>"

# External Document Tables for Legal References

class Nomos(Base):
    """Greek laws (nomoi) model"""
    __tablename__ = 'nomoi'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    type = Column(String(100))  # law type classification
    content = Column(Text)  # Extracted content
    content_cleaned = Column(Text)  # Cleaned/processed content
    extraction_method = Column(String(100))  # Method used for content extraction
    badness_score = Column(Float)  # Quality score from rust processor (numeric)
    greek_percentage = Column(Float)  # Percentage of Greek content (numeric)
    english_percentage = Column(Float)  # Percentage of English content (numeric)
    publication_date = Column(DateTime)  # Official publication date
    law_number = Column(String(100))  # Official law number
    source = Column(String(100))  # Source (e.g., 'ΦΕΚ', 'et.gr')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Nomos(title='{self.title[:50]}...', law_number='{self.law_number}')>"

class YpourgikiApofasi(Base):
    """Ministerial decisions (ypourgikes apofaseis) model"""
    __tablename__ = 'ypourgikes_apofaseis'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    type = Column(String(100))  # decision type classification
    content = Column(Text)  # Extracted content
    content_cleaned = Column(Text)  # Cleaned/processed content
    extraction_method = Column(String(100))  # Method used for content extraction
    badness_score = Column(Float)  # Quality score from rust processor (numeric)
    greek_percentage = Column(Float)  # Percentage of Greek content (numeric)
    english_percentage = Column(Float)  # Percentage of English content (numeric)
    publication_date = Column(DateTime)  # Official publication date
    decision_number = Column(String(100))  # Official decision number
    ministry = Column(String(255))  # Issuing ministry
    source = Column(String(100))  # Source (e.g., 'ΦΕΚ', 'ministry website')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<YpourgikiApofasi(title='{self.title[:50]}...', decision_number='{self.decision_number}')>"

class ProedrikiDiatagma(Base):
    """Presidential decrees (proedrika diatagmata) model"""
    __tablename__ = 'proedrika_diatagmata'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    type = Column(String(100))  # decree type classification
    content = Column(Text)  # Extracted content
    content_cleaned = Column(Text)  # Cleaned/processed content
    extraction_method = Column(String(100))  # Method used for content extraction
    badness_score = Column(Float)  # Quality score from rust processor (numeric)
    greek_percentage = Column(Float)  # Percentage of Greek content (numeric)
    english_percentage = Column(Float)  # Percentage of English content (numeric)
    publication_date = Column(DateTime)  # Official publication date
    decree_number = Column(String(100))  # Official decree number
    source = Column(String(100))  # Source (e.g., 'ΦΕΚ', 'presidency.gr')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<ProedrikiDiatagma(title='{self.title[:50]}...', decree_number='{self.decree_number}')>"

class EuRegulation(Base):
    """EU regulations model"""
    __tablename__ = 'eu_regulations'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    type = Column(String(100))  # regulation type classification
    content = Column(Text)  # Extracted content
    content_cleaned = Column(Text)  # Cleaned/processed content
    extraction_method = Column(String(100))  # Method used for content extraction
    badness_score = Column(Float)  # Quality score from rust processor (numeric)
    greek_percentage = Column(Float)  # Percentage of Greek content (numeric)
    english_percentage = Column(Float)  # Percentage of English content (numeric)
    publication_date = Column(DateTime)  # Official publication date
    regulation_number = Column(String(100))  # Official regulation number (e.g., '2024/903')
    eu_year = Column(Integer)  # Year of regulation
    source = Column(String(100))  # Source (e.g., 'EUR-Lex', 'eur-lex.europa.eu')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<EuRegulation(title='{self.title[:50]}...', regulation_number='{self.regulation_number}')>"

class EuDirective(Base):
    """EU directives model"""
    __tablename__ = 'eu_directives'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    type = Column(String(100))  # directive type classification
    content = Column(Text)  # Extracted content
    content_cleaned = Column(Text)  # Cleaned/processed content
    extraction_method = Column(String(100))  # Method used for content extraction
    badness_score = Column(Float)  # Quality score from rust processor (numeric)
    greek_percentage = Column(Float)  # Percentage of Greek content (numeric)
    english_percentage = Column(Float)  # Percentage of English content (numeric)
    publication_date = Column(DateTime)  # Official publication date
    directive_number = Column(String(100))  # Official directive number (e.g., '2019/1024')
    eu_year = Column(Integer)  # Year of directive
    source = Column(String(100))  # Source (e.g., 'EUR-Lex', 'eur-lex.europa.eu')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<EuDirective(title='{self.title[:50]}...', directive_number='{self.directive_number}')>"

def init_db(db_url=None):
    """Initialize the database, creating all tables"""
    if db_url is None:
        # Use the project root directory for the database
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(project_root, 'deliberation_data_gr.db')
        db_url = f'sqlite:///{db_path}'
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session

if __name__ == "__main__":
    # Create the database
    engine, Session = init_db()
    print("Database initialized with all tables created.")
