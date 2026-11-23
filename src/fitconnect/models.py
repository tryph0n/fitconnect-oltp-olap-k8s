"""FitConnect OLTP data models."""

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import DATE
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "User"

    UserID = Column(Integer, primary_key=True, autoincrement=True)
    Username = Column(String, nullable=False)
    Email = Column(String, nullable=False)
    Password = Column(String, nullable=False)
    JoinDate = Column(DATE, nullable=False)
    LastLogin = Column(DATE)
    AccountStatus = Column(String, nullable=False)


class Profile(Base):
    __tablename__ = "Profile"

    ProfileID = Column(Integer, primary_key=True, autoincrement=True)
    UserID = Column(Integer, ForeignKey("User.UserID"), nullable=False)
    FirstName = Column(String, nullable=False)
    LastName = Column(String, nullable=False)
    BirthDate = Column(DATE)
    Gender = Column(String)
    Height = Column(Float)
    CurrentWeight = Column(Float)
    TargetWeight = Column(Float)
    FitnessGoal = Column(String)
    ActivityLevel = Column(String)


class Exercise(Base):
    __tablename__ = "Exercise"

    ExerciseID = Column(Integer, primary_key=True, autoincrement=True)
    Name = Column(String, nullable=False)
    Description = Column(Text)
    Category = Column(String)
    MuscleGroup = Column(String)
    DifficultyLevel = Column(String)
    DemoVideoURL = Column(String)


class Workout(Base):
    __tablename__ = "Workout"

    WorkoutID = Column(Integer, primary_key=True, autoincrement=True)
    UserID = Column(Integer, ForeignKey("User.UserID"), nullable=False)
    WorkoutPlanID = Column(Integer, nullable=True)
    WorkoutDate = Column(DATE, nullable=False)
    Duration = Column(Integer)
    CaloriesBurned = Column(Float)
    Notes = Column(Text)
    Rating = Column(Integer)
    CompletionStatus = Column(String)


class WorkoutExercise(Base):
    __tablename__ = "WorkoutExercise"

    WorkoutID = Column(Integer, ForeignKey("Workout.WorkoutID"), primary_key=True)
    ExerciseID = Column(Integer, ForeignKey("Exercise.ExerciseID"), primary_key=True)
    SetCount = Column(Integer)
    RepCount = Column(Integer)
    Weight = Column(Float)
    Duration = Column(Integer)
    Notes = Column(Text)
    Order = Column(Integer)


TABLES = ("User", "Profile", "Exercise", "Workout", "WorkoutExercise")
