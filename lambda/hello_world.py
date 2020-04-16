# -*- coding: utf-8 -*-

# This sample demonstrates handling intents from an Alexa skill using the Alexa Skills Kit SDK for Python.
# Please visit https://alexa.design/cookbook for additional examples on implementing slots, dialog management,
# session persistence, api calls, and more.
# This sample is built using the handler classes approach in skill builder.
import uuid
import logging
import json
import dateutil.parser
import datetime
import functools
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

STUDENT_PROFILE_NAMESPACE = "Alexa.Education.Profile.Student"
COURSEWORK_NAMESPACE = "Alexa.Education.Coursework"
ANNOUNCEMENTS_NAMESPACE = "Alexa.Education.School.Communication"

def student_profile_handler(request, creds, context):
    service = build('classroom', 'v1', credentials=creds)
    user_profile = service.userProfiles().get(userId="me").execute()
    logger.info(json.dumps(user_profile))

    return {
        "response": {
            "header": {
                "namespace": STUDENT_PROFILE_NAMESPACE,
                "name": "GetResponse",
                "messageId": str(uuid.uuid4()),
                "interfaceVersion": "1.0"
            },
            "payload": {
                "paginationContext": {
                    "totalCount": 1
                },
                "studentProfiles": [
                    {
                        "id": user_profile['id'],
                        "accountRelationType": "SELF",
                        "name": {
                            "given": user_profile['name']['givenName'],
                            "family": user_profile['name']['familyName'],
                            "full": user_profile['name']['fullName']
                        }
                    }
                ]
            }
        }
    }


def _handle_course_works(request_id, response, exception,\
    service, course_name, due_start, due_end, all_course_works):
    logger.info("Original course work: {}".format(json.dumps(response)))
    for course_work in response.get("courseWork", []):
        if course_work.get("workType", "") != "ASSIGNMENT" or "dueDate" not in course_work:
            continue

        course_work_id = course_work['id']
        course_id = course_work['courseId']
        cw_due_date_obj = course_work['dueDate']
        cw_due_time_obj = course_work['dueTime']
        cw_due_date = datetime.datetime(
            year=cw_due_date_obj['year'],
            month=cw_due_date_obj['month'],
            day=cw_due_date_obj['day'],
            hour=cw_due_time_obj['hours'],
            minute=cw_due_time_obj['minutes'],
            tzinfo=datetime.timezone.utc)

        # Apparently there is a difference between how Alexa counts as
        # "today" and how google counts as "today"
        if cw_due_date < due_start or cw_due_date > due_end:
            continue

        converted_cw = {
            "id": course_work_id,
            "courseId": course_id,
            "courseName": course_name,
            "title": course_work['title'],
            "description": course_work.get('description', ""),
            "type": "ASSIGNMENT",
            "submissionState": "MISSING",
            "dueTime": cw_due_date.isoformat(),
            "publishedTime": course_work['creationTime']
        }
        logger.info("Converted course work: {}".format(converted_cw))
        all_course_works.append(converted_cw)


def _handle_submission(request_id, response, exception, all_submissions):
    logger.info("Original submissions: {}".format(json.dumps(response)))
    submissions = response.get("studentSubmissions", [])
    if len(submissions) > 0:
        first_submission = submissions[0]
        course_work_id = first_submission['courseWorkId']
        all_submissions[course_work_id] = submissions

def coursework_handler(request, creds, context):
    service = build('classroom', 'v1', credentials=creds)
    student_id = request['query']['matchAll']['studentId']
    courses = service.courses().list(studentId=student_id, fields="courses(id,name)").execute()
    logger.info("Courses: {}".format(json.dumps(courses)))

    due_time = request['query']['matchAll']['dueTime']
    due_start_str, due_end_str = due_time['start'], due_time['end']
    due_start = dateutil.parser.isoparse(due_start_str)
    due_end = dateutil.parser.isoparse(due_end_str)

    pagination_context = request['paginationContext']
    max_results = pagination_context['maxResults']

    all_course_works, num_course_works = [], 0
    course_ids = [c['id'] for c in courses.get("courses", [])]

    batch_request = service.new_batch_http_request()
    for course in courses.get("courses", []):
        course_id, course_name = course['id'], course['name']
        batch_request.add(service.courses().courseWork().list(
            courseId=course_id, orderBy="dueDate desc", pageSize=max_results,
            fields="courseWork(id,workType,courseId,dueDate,dueTime,title,description,creationTime)"),
            callback=functools.partial(_handle_course_works,\
                service=service,
                course_name=course_name,
                due_start=due_start,
                due_end=due_end,
                all_course_works=all_course_works))
    batch_request.execute()

    submissions_batch_request = service.new_batch_http_request()
    all_submissions = {}
    handle_submissions_partial = functools.partial(_handle_submission, all_submissions=all_submissions)
    for course_work in all_course_works:
        course_work_id, course_id = course_work['id'], course_work['courseId']
        submission_request = service.courses().courseWork().studentSubmissions().list(
            courseId=course_id,
            courseWorkId=course_work_id,
            userId=student_id
        )
        submissions_batch_request.add(submission_request, callback=handle_submissions_partial)
    submissions_batch_request.execute()

    for course_work in all_course_works:
        course_work_id = course_work['id']
        submissions = all_submissions.get(course_work_id, [])
        course_work["submissionState"] = "NOT_SUBMITTED" if len(submissions) <= 0 else "SUBMITTED"

    return {
        "response": {
            "header": {
                "namespace": COURSEWORK_NAMESPACE,
                "name": "GetResponse",
                "interfaceVersion": "1.0",
                "messageId": str(uuid.uuid4())
            },
            "payload": {
                "paginationContext": {
                    "totalCount": len(all_course_works)
                },
                "coursework": all_course_works
            }
        }
    }

def _handle_announcement(request_id, response, exception, all_announcements):
    start = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    start = start.replace(tzinfo=datetime.timezone.utc)
    announcements = response.get("announcements", [])
    for announcement in announcements:
        update_time = dateutil.parser.isoparse(announcement['updateTime']).replace(tzinfo=datetime.timezone.utc)
        if update_time < start:
            continue
        all_announcements.append(announcement)

def _handle_user_profile(request_id, response, exception, all_users):
    logger.info("User profile: {}".format(json.dumps(response)))
    logger.info("Exception: {}".format(exception))
    if response:
        all_users[response['id']] = response

def _extract_name(user):
    if user:
        name = user['name']
        return name.get("fullName", name.get("givenName", "Unknown user"))
    return "Unknown user"

def announcements_handler(request, creds, context):
    pagination_context = request['paginationContext']
    max_results = pagination_context['maxResults']
    query = request['query']
    student_id = query['matchAll'].get('studentId', "me")

    service = build('classroom', 'v1', credentials=creds)
    courses = service.courses().list(studentId=student_id, fields="courses(id)").execute()

    all_announcements = []
    announcements_partial = functools.partial(_handle_announcement, all_announcements=all_announcements)
    course_ids = [c['id'] for c in courses.get("courses", [])]
    batch_request = service.new_batch_http_request()
    for course_id in course_ids:
        batch_request.add(service.courses().announcements().list(courseId=course_id), callback=announcements_partial)
    batch_request.execute()
    logger.info("Announcements: {}".format(json.dumps(all_announcements)))

    all_users = {}
    user_profiles_partial = functools.partial(_handle_user_profile, all_users=all_users)
    user_ids = set([a['creatorUserId'] for a in all_announcements])
    user_batch_requests = service.new_batch_http_request()
    for user_id in user_ids:
        user_batch_requests.add(service.userProfiles().get(userId=user_id, fields="id,name"), callback=user_profiles_partial)
    user_batch_requests.execute()

    converted_announcements = [
        {
            "id": a['id'],
            'type': 'GENERIC_FROM',
            'kind': 'ANNOUNCEMENT',
            'from': _extract_name(all_users.get(a['creatorUserId'])),
            'content': {
                'type': 'PLAIN_TEXT',
                'text': a['text']
            },
            'publishedTime': a['updateTime']
        } for a in all_announcements[:max_results]
    ]
    logger.info("Converted announcements: {}".format(json.dumps(converted_announcements)))

    return {
        "response": {
            "header": {
                "namespace": ANNOUNCEMENTS_NAMESPACE,
                "name": "GetResponse",
                "interfaceVersion": "1.0",
                "messageId": str(uuid.uuid4())
            },
            "payload": {
                "paginationContext": {
                    "totalCount": len(converted_announcements)
                },
                "schoolCommunications": converted_announcements
            }
        }
    }

HANDLER_MAP = {
    STUDENT_PROFILE_NAMESPACE: student_profile_handler,
    COURSEWORK_NAMESPACE: coursework_handler,
    ANNOUNCEMENTS_NAMESPACE: announcements_handler
}

def handler(event, context):
    logger.info(json.dumps(event))
    request = event['request']

    header = request['header']
    namespace, name = header['namespace'], header['name']

    authorization = request['authorization']
    creds = Credentials(authorization['token'])

    real_handler = HANDLER_MAP[namespace]
    return real_handler(request['payload'], creds, context)