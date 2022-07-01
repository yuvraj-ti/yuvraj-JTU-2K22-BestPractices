from rest_framework.exceptions import APIException


class Unauthorized_User_Exception(APIException):
    status_code = 404
    default_detail = "Not Found"
    default_code = "Records unavailable"