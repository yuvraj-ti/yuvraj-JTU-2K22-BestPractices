# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from decimal import Decimal
import pandas as pd
import numpy as np
import urllib.request
import concurrent.futures
from datetime import datetime

from django.http import HttpResponse
from django.contrib.auth.models import User

# Create your views here.
from rest_framework.permissions import AllowAny
from rest_framework.decorators import *
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework import status

from restapi.models import *
from restapi.serializers import *
from restapi.custom_exception import *



def index(_request)-> HttpResponse:
    return HttpResponse("Hello, world. You're at Rest.")


@api_view(['POST'])
def logout(request)->Response:
    request.user.auth_token.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
def balance(request) -> Response:
    user = request.user
    expenses = Expenses.objects.filter(users__in=user.expenses.all())
    final_balance = {}
    for expense in expenses:
        expense_balances = normalize(expense)
        for eb in expense_balances:
            from_user = eb['from_user']
            to_user = eb['to_user']
            if from_user == user.id:
                final_balance[to_user] = final_balance.get(to_user, 0) - eb['amount']
            if to_user == user.id:
                final_balance[from_user] = final_balance.get(from_user, 0) + eb['amount']
    final_balance = {k: v for k, v in final_balance.items() if v != 0}

    response = [{"user": k, "amount": int(v)} for k, v in final_balance.items()]
    return Response(response, status=status.HTTP_200_OK)


def normalize(expense) -> list:
    user_balances = expense.users.all()
    dues = {}
    for user_balance in user_balances:
        dues[user_balance.user] = dues.get(user_balance.user, 0) + user_balance.amount_lent \
                                  - user_balance.amount_owed
    dues = [(k, v) for k, v in sorted(dues.items(), key=lambda item: item[1])]
    start = 0
    end = len(dues) - 1
    balances = []
    while start < end:
        amount = min(abs(dues[start][1]), abs(dues[end][1]))
        user_balance = {"from_user": dues[start][0].id, "to_user": dues[end][0].id, "amount": amount}
        balances.append(user_balance)
        dues[start] = (dues[start][0], dues[start][1] + amount)
        dues[end] = (dues[end][0], dues[end][1] - amount)
        if dues[start][1] == 0:
            start += 1
        else:
            end -= 1
    return balances


class user_view_set(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = User_Serializer
    permission_classes = (AllowAny,)


class category_view_set(ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = Category_Serializer
    http_method_names = ['get', 'post']


class group_view_set(ModelViewSet):
    queryset = Groups.objects.all()
    serializer_class = Group_Serializer

    def get_queryset(self):
        user = self.request.user
        groups = user.members.all()
        if self.request.query_params.get('q', None) is not None:
            groups = groups.filter(name__icontains=self.request.query_params.get('q', None))
        return groups

    def create(self, request, *args, **kwargs) -> Response:
        user = self.request.user
        data = self.request.data
        group = Groups(**data)
        group.save()
        group.members.add(user)
        serializer = self.get_serializer(group)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(methods=['put'], detail=True)
    def members(self, request, pk=None)->Response:
        group = Groups.objects.get(id=pk)
        if group not in self.get_queryset():
            raise Unauthorized_User_Exception()
        body = request.data
        if body.get('add', None) is not None and body['add'].get('user_ids', None) is not None:
            added_ids = body['add']['user_ids']
            for user_id in added_ids:
                group.members.add(user_id)
        if body.get('remove', None) is not None and body['remove'].get('user_ids', None) is not None:
            removed_ids = body['remove']['user_ids']
            for user_id in removed_ids:
                group.members.remove(user_id)
        group.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=['get'], detail=True)
    def expenses(self, _request, pk=None)->Response:
        group = Groups.objects.get(id=pk)
        if group not in self.get_queryset():
            raise Unauthorized_User_Exception()
        expenses = group.expenses_set
        serializer = Expenses_Serializer(expenses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(methods=['get'], detail=True)
    def balances(self, _request, pk=None)->Response:
        group = Groups.objects.get(id=pk)
        if group not in self.get_queryset():
            raise Unauthorized_User_Exception()
        expenses = Expenses.objects.filter(group=group)
        dues = {}
        for expense in expenses:
            user_balances = User_Expense.objects.filter(expense=expense)
            for user_balance in user_balances:
                dues[user_balance.user] = dues.get(user_balance.user, 0) + user_balance.amount_lent \
                                          - user_balance.amount_owed
        dues = [(k, v) for k, v in sorted(dues.items(), key=lambda item: item[1])]
        start = 0
        end = len(dues) - 1
        balances = []
        while start < end:
            amount = min(abs(dues[start][1]), abs(dues[end][1]))
            amount = Decimal(amount).quantize(Decimal(10)**-2)
            user_balance = {"from_user": dues[start][0].id, "to_user": dues[end][0].id, "amount": str(amount)}
            balances.append(user_balance)
            dues[start] = (dues[start][0], dues[start][1] + amount)
            dues[end] = (dues[end][0], dues[end][1] - amount)
            if dues[start][1] == 0:
                start += 1
            else:
                end -= 1

        return Response(balances, status=status.HTTP_200_OK)


class expenses_view_set(ModelViewSet):
    queryset = Expenses.objects.all()
    serializer_class = Expenses_Serializer

    def get_queryset(self):
        user = self.request.user
        if self.request.query_params.get('q', None) is not None:
            expenses = Expenses.objects.filter(users__in=user.expenses.all())\
                .filter(description__icontains=self.request.query_params.get('q', None))
        else:
            expenses = Expenses.objects.filter(users__in=user.expenses.all())
        return expenses

@api_view(['post'])
@authentication_classes([])
@permission_classes([])
def logProcessor(request) -> Response:
    data = request.data
    num_threads = data['parallelFileProcessingCount']
    log_files = data['logFiles']
    if num_threads <= 0 or num_threads > 30:
        return Response({"status": "failure", "reason": "Parallel Processing Count out of expected bounds"},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(log_files) == 0:
        return Response({"status": "failure", "reason": "No log files provided in request"},
                        status=status.HTTP_400_BAD_REQUEST)
    logs = multi_Threaded_Reader(urls=data['logFiles'], num_threads=data['parallelFileProcessingCount'])
    sorted_logs = sort_by_time_stamp(logs)
    cleaned = transform(sorted_logs)
    data = aggregate(cleaned)
    response = response_format(data)
    return Response({"response":response}, status=status.HTTP_200_OK)

def sort_by_time_stamp(logs)-> list:
    data = []
    for log in logs:
        data.append(log.split(" "))
    # print(data)
    data = sorted(data, key=lambda elem: elem[1])
    return data

def response_format(raw_data)->list:
    response = []
    for timestamp, data in raw_data.items():
        entry = {'timestamp': timestamp}
        logs = []
        data = {k: data[k] for k in sorted(data.keys())}
        for exception, count in data.items():
            logs.append({'exception': exception, 'count': count})
        entry['logs'] = logs
        response.append(entry)
    return response

def aggregate(cleaned_logs)->dict:
    data = {}
    for log in cleaned_logs:
        [key, text] = log
        value = data.get(key, {})
        value[text] = value.get(text, 0)+1
        data[key] = value
    return data


def transform(logs)->list:
    result = []
    for log in logs:
        [_, timestamp, text] = log
        text = text.rstrip()
        timestamp = datetime.utcfromtimestamp(int(int(timestamp)/1000))
        hours, minutes = timestamp.hour, timestamp.minute
        key = ''

        if minutes >= 45:
            if hours == 23:
                key = "{:02d}:45-00:00".format(hours)
            else:
                key = "{:02d}:45-{:02d}:00".format(hours, hours+1)
        elif minutes >= 30:
            key = "{:02d}:30-{:02d}:45".format(hours, hours)
        elif minutes >= 15:
            key = "{:02d}:15-{:02d}:30".format(hours, hours)
        else:
            key = "{:02d}:00-{:02d}:15".format(hours, hours)

        result.append([key, text])
        print(key)

    return result


def reader(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as conn:
        return conn.read()


def multi_Threaded_Reader(urls, num_threads)->list:
    """
        Read multiple files through HTTP
    """
    result = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        future_to_url = {executor.submit(load_url, url, HTTP_TIMEOUT): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            data = future.result()
            result.extend(data.split("\n"))    
    result = sorted(result, key=lambda elem:elem[1])
    return result
