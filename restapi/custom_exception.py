from rest_framework.exceptions import APIException
from rest_framework import status

class Unauthorized_User_Exception(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Not Found"
    default_code = "Records unavailable"