# Overview:

An lms system mvp that has 3 roles.
- Teacher
- student
- admin

## Tech Stack:

### frontend: 
- react.js
### backend:
- fastapi
- supabase (database, auth)
- for video streaming: Mux api

## High Level view:

### frontend:
- components -> api layer (api layer calls the backend)

### supabase database:
- auth.users (already created)
- teachers table(
    teacher_id uuid
    profile_id -> references user_id(auth.users) FK,
    
)
- courses table(
    course_id uuid,
    teacher_id references teacher_id(teachers table),
    course_name text,
    data_created datetime,
    status (active | inactive)
    

)
- lessons table(
    lesson_id uuid,
    course_id references course_id(courses table),
    lesson_number integer (for each course, lessons start from 1)
    lesson_body text (markdown text)
    video_url (referencing to mux video url, this is optional)
)
- mux table(
    mux_video_id uuid,
    video_url (url or whatever the link mux provides us, we need to look into this),
    ....
)
- students table(
    student_id uuid,
    profile_id -> references user_id(auth.users) FK,
    
)
- student_registered_courses tables(
    record_id uuid,
    student_id references student_id(students table),
    course_id references course_id(courses table)

)
- admin table(
    admin_id uuid,
    profile_id -> references user_id(auth.users) FK,
    analytics ( total students enrolled, total teachers, each teacher's courses, etc),
    status (approved | not approved)

)

how this works? 
- new user signs up (enters username, email, and password in the frontend, selects role
- new student, when auth.user record created, launch trigger function that creates student record in its table
- new teacher, when auth.user record created, launch trigger function that creates teacher record in its table
- new admin, when auth.user record created, launch trigger function that creates admin record in its table but sets status (not approved) unless a previous admin approves it

### backend:
- sign up: frontend sends credentials to backend, backend creates a sign up. Dont directly sign up from the browser, meaning browser -> supabse, no. Rather, browser -> backend -> supabase. 
- sign in and auth: option for "teacher login" or "student login". Whatever the user selects, match it with the records in auth.users, and then in the specific records, i.e student table records or teacher table records. Similarly for admin. Release jwt token with permissions, and dependency check the role before api execution. 
- create the apis router layer for students, teachers, and admin. 
- the router layer calls functions from a services/ layer.

### Frontend:
- use react with jsx.
- make the UI modern and interactive.
- a dashboard showing all the courses.
- student can enroll in a course
- teacher can create and delete courses
- each course contains lessons, each lesson can have a video url and a lesson body which is markdown text. Teacher can save this, students can read.
- student can see enrolled courses
- admin can see total students, total teachers, and total courses by each teacher. he can also see student names against each course.

### Approach:
- you will act as the orchestrator. One agent implements the frontend. Another agent implements the backend. You overlook them both and check if they are making any mistakes or no.
- use supabase MCP for databases and other stuff. Look at the documentation for sdks and stuff like that. Also look at mux docs https://www.mux.com/docs
