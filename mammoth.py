import requests
import time
import json
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from request import Request
import keyboard
import threading
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Job(Base):
    __tablename__ = 'jobs'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, nullable=False)
    created_date = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    modified_date = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    finished_date = Column(DateTime(timezone=True))
    status = Column(String)

    events = relationship("Event", backref="job")

class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey('jobs.id'), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    message = Column(Text)  # Use Text for potentially longer messages

# Load environment variables
DB_NAME = os.getenv('DB_NAME')
DB_HOST = os.getenv('DB_HOST')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASS')

DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}'

engine = create_engine(DATABASE_URI)
Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)

class Mammoth:
    def __init__(self, noggin_url, workers=None):
        self.noggin_url = noggin_url
        self.auth_key = os.getenv('AUTHORIZATION_KEY', 'default_key')  # Default value if not set
        self.workers = workers if workers is not None else multiprocessing.cpu_count()
        self.stop_signal = threading.Event()  # Use an event to signal workers to stop

    def fetch_next_unhandled_request(self, session, noggin_url, auth_key):
        headers = {"Authorization": f"Bearer {auth_key}"}
        try:
            response = requests.get(f"{noggin_url}/request/next-unhandled", headers=headers)
            if response.status_code == 200:
                data = response.json()

                # Create a Job record
                job = Job(request_id=data.get('id'), status='Pending')
                session.add(job)
                session.commit()

                # Return both the Request and Job ID for further processing
                return Request(
                    id=data.get('id'),
                    timestamp=data.get('timestamp'),  
                    source_ip=data.get('source_ip'),
                    user_agent=data.get('user_agent'),
                    method=data.get('method'),
                    request_url=data.get('request_url'),
                    request_raw=data.get('request_raw'),
                    is_handled=data.get('is_handled')
                ), job.id
            else:
                print("Failed to fetch unhandled request:", response.status_code)
                time.sleep(5)
                return None, None
        except requests.exceptions.RequestException as e:
            print("Error fetching unhandled request:", e)
            return None, None


    def process_request_data(self, session, request, job_id):
        if request and request.request_raw:
            payload = json.loads(request.request_raw)
            thread_id = threading.get_ident()  # Get the current thread's identifier
            
            # Log the start of processing as an event
            start_event = Event(job_id=job_id, message=f'Start processing request {request.id} in thread {thread_id}.')
            session.add(start_event)

            # Simulate some work
            import random
            for i in range(random.randint(1, 5)):
                print(f"Request: {request.id}\tThread:{thread_id}\tDoing some heavy work...")
                time.sleep(random.randint(1, 5))

                # Optionally log progress events here

            # Mark job as completed
            job = session.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = 'Completed'
                job.finished_date = datetime.now(timezone.utc)
                session.add(job)
            
            # Log the completion of processing as an event
            completion_event = Event(job_id=job_id, message=f'Completed processing request {request.id} in thread {thread_id}.')
            session.add(completion_event)

            session.commit()
            
            return True
        return False

    def session_factory(self):
        # Factory method to create a new SQLAlchemy session
        return Session()

    def run(self):
        # Setup a listener for the 'q' keypress in a background thread
        def on_q_pressed(event):
            if event.name == 'q':
                print("\n'q' pressed, stopping all workers...")
                self.stop_signal.set()

        keyboard.on_press(on_q_pressed)

        def worker_task(session_factory, noggin_url, auth_key, stop_signal):
            session = session_factory()
            while not stop_signal.is_set():
                request, job_id = self.fetch_next_unhandled_request(session, noggin_url, auth_key)
                if request and job_id:
                    self.process_request_data(session, request, job_id)
                    # Assuming request.mark_as_handled() updates the request's status
            session.close()

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            for _ in range(self.workers):
                executor.submit(worker_task, self.session_factory, self.noggin_url, self.auth_key, self.stop_signal)

        print("All workers have been stopped.")

if __name__ == "__main__":
    NOGGIN_URL = "http://127.0.0.1:5000"
    NUM_WORKERS = 2  # Adjust as needed.

    mammoth_app = Mammoth(NOGGIN_URL, NUM_WORKERS)
    print("Starting Mammoth application...")
    mammoth_app.run()
