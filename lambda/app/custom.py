from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk.standard import StandardSkillBuilder
from ask_sdk_core.utils import is_request_type
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, ListAttribute

import datetime
import uuid
import boto3


class UserMapping(Model):
    class Meta:
        table_name = "UserMapping"
        region = "us-east-1"
    google_user_id = UnicodeAttribute(hash_key=True)
    alexa_user_id = UnicodeAttribute()
    registration_ids = ListAttribute()


class PermissionChangedEventHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        return is_request_type("AlexaSkillEvent.SkillPermissionChanged")(handler_input)\
            or is_request_type("AlexaSkillEvent.SkillPermissionAccepted")(handler_input)

    def handle(self, handler_input: HandlerInput):
        attributes_manager = handler_input.attributes_manager
        request_envelope = handler_input.request_envelope

        alexa_context = request_envelope.context
        system_context = alexa_context.system
        api_access_token = system_context.user.access_token
        alexa_user_id = system_context.user.user_id

        request = request_envelope.request
        permission_body = request.body
        accepted_permissions = set(p.scope for p in permission_body.accepted_permissions)
        if accepted_permissions:
            print("Accepted permissions: {}".format(accepted_permissions))
            user_attributes = attributes_manager.persistent_attributes
            if "alexa::devices:all:notifications:write" in accepted_permissions:

                print("Access token: {}".format(api_access_token))
                creds = Credentials(api_access_token)
                service = build('classroom', 'v1', credentials=creds)

                user_profile = service.userProfiles().get(userId="me").execute()
                google_user_id = user_profile['id']

                courses = service.courses().list(studentId="me", fields="courses(id,name)").execute().get("courses", [])

                registration_ids = []
                batch_registration_request = service.new_batch_http_request()
                for course in courses:
                    print("Registering notifications for {}: {}".format(course['id'], course['name']))
                    registration_id = str(uuid.uuid4())
                    registration_ids.append(registration_id)
                    batch_registration_request.add(service.registrations().create(body={
                        "feed": {
                            "feedType": "COURSE_WORK_CHANGES",
                            "courseWorkChangesInfo": {
                                "courseId": course['id']
                            }
                        },
                        "cloudPubsubTopic": {
                            "topicName": "projects/quickstart-1586973831483/topics/ClassroomNotifications"
                        }
                    }), callback=self._handle_registration_created)
                batch_registration_request.execute()

                new_user_mapping = UserMapping(google_user_id, alexa_user_id=alexa_user_id,\
                    registration_ids=registration_ids)
                new_user_mapping.save()
                user_attributes["googleUserId"] = google_user_id
                user_attributes["registrationIds"] = registration_ids
            else:
                registration_ids = user_attributes.get("registrationIds", [])
                for registration_id in registration_ids:
                    service.registrations().delete(registrationId=registration_id).execute()
                user_attributes["registrationIds"] = []
                user_attributes["googleUserId"] = None

        attributes_manager.save_persistent_attributes()

    def _handle_registration_created(self, request_id, response, exception):
        print("Registration error: {}".format(exception))
        print("Registration error: {}".format(exception.error_details))
        print("Registration created: {}".format(response))


class ProactiveSubscriptionChanged(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("AlexaSkillEvent.ProactiveSubscriptionChanged")(handler_input)

    def handle(self, handler_input):
        print("Proactive subscription changed event received")


class AccountLinkedEventHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("AlexaSkillEvent.SkillAccountLinked")(handler_input)

    def handle(self, handler_input):
        print("Account linked")


def get_handler():
    sb = StandardSkillBuilder(table_name="GoogleClassroomStates",\
        auto_create_table=True)
    sb.add_request_handler(PermissionChangedEventHandler())
    sb.add_request_handler(ProactiveSubscriptionChanged())
    sb.add_request_handler(AccountLinkedEventHandler())
    return sb.lambda_handler()
