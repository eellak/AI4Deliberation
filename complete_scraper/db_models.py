#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, create_engine
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
    is_finished = Column(Boolean, default=False)
    url = Column(String(255), nullable=False, unique=True)
    description = Column(Text)

    total_comments = Column(Integer, default=0)
    accepted_comments = Column(Integer, default=0)
    ministry_id = Column(Integer, ForeignKey('ministries.id'))
    
    # Relationships
    ministry = relationship("Ministry", back_populates="consultations")
    articles = relationship("Article", back_populates="consultation")
    documents = relationship("Document", back_populates="consultation")
    
    def __repr__(self):
        return f"<Consultation(post_id='{self.post_id}', title='{self.title[:50]}...')>"

class Article(Base):
    """Article model - parent of comments"""
    __tablename__ = 'articles'
    
    id = Column(Integer, primary_key=True)
    post_id = Column(String(50), nullable=False)
    title = Column(String(500), nullable=False)
    content = Column(Text)
    url = Column(String(255), nullable=False, unique=True)
    consultation_id = Column(Integer, ForeignKey('consultations.id'))
    
    # Relationships
    consultation = relationship("Consultation", back_populates="articles")
    comments = relationship("Comment", back_populates="article")
    
    def __repr__(self):
        return f"<Article(post_id='{self.post_id}', title='{self.title[:50]}...')>"

class Comment(Base):
    """Comment model"""
    __tablename__ = 'comments'
    
    id = Column(Integer, primary_key=True)
    comment_id = Column(String(50))
    username = Column(String(255), nullable=False)
    date = Column(DateTime)
    content = Column(Text, nullable=False)
    article_id = Column(Integer, ForeignKey('articles.id'))
    
    # Relationships
    article = relationship("Article", back_populates="comments")
    
    def __repr__(self):
        return f"<Comment(id={self.id}, author='{self.author}', date='{self.date}')>"

class Document(Base):
    """Document model"""
    __tablename__ = 'documents'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False, unique=True)
    type = Column(String(100))  # law_draft, analysis, deliberation_report, or other
    consultation_id = Column(Integer, ForeignKey('consultations.id'))
    
    # Relationships
    consultation = relationship("Consultation", back_populates="documents")
    
    def __repr__(self):
        return f"<Document(title='{self.title}', type='{self.type}')>"

def init_db(db_url='sqlite:///deliberation_data.db'):
    """Initialize the database, creating all tables"""
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session

if __name__ == "__main__":
    # Create the database
    engine, Session = init_db()
    print("Database initialized with all tables created.")
