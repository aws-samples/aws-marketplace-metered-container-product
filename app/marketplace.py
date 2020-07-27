#!/usr/bin/python

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
import os
import sys
import threading
from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal
from time import sleep

import boto3
import pytz
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class MeterUsageIntegration:

    _SEND_DIMENSIONS_AFTER = 3600

    # Initializes the integration and starts a thread to send the metering
    # information to AWS Marketplace hourly
    def __init__(self,
                 region_name,
                 product_code,
                 dimensions_storage,
                 max_send_stop=2,
                 max_send_warning=1):
        self._product_code = product_code
        self._max_send_stop = max_send_stop
        self._max_send_warning = max_send_warning
        self.state = State(max_send_stop, max_send_warning,
                           self._SEND_DIMENSIONS_AFTER)
        self._mms_client = boto3.client('meteringmarketplace',
                                        region_name=region_name)
        self._dimensions_storage = dimensions_storage
        self._initializing = True
        try:
            self._check_connectivity_and_dimensions()
        except ClientError as err:
            self.state.type = "init"
            self.state.add_error(err)
            logger.error(err)
        except:
            self.state.type = "init"
            self.state.add(f"{sys.exc_info()[1]}")
            logger.error((f"{sys.exc_info()[1]}"))

        t = threading.Thread(target=self.run)
        t.start()

    def run(self):
        logger.info("Initializing")
        if self.state.type != "init":
            while True:
                self.meter_usages()
                self.update_state()
                if self.state.type == "stop":
                    message = f"The usage couldn't be sent after {self._max_send_stop } tries. Please check that your product has a way to reach the internet."
                    self.state.add(message)
                    logger.error(message)
                logger.info("Going to sleep")
                sleep(self._SEND_DIMENSIONS_AFTER)

    def get_consumption(self):
        """ Returns all the dimensions from the DynamoDB table """
        return {
            "dimensions":
            Utils.sanitize(self._dimensions_storage.get_dimensions())
        }

    def get_state(self):
        """ Returns the state """
        return {"state": Utils.sanitize(self.state)}

    def meter_usages(self, dry_run=False):
        """ Iterates over all dimensions on the DynamoDB table and sends it to Marketplace Metering Service (MMS) using the meter_usage method. """
        logger.info(f"meter_usages: dry_run={dry_run}")
        responses = []
        for d in self._dimensions_storage.get_dimensions():
            # If you call meter_usage at start time with 0 as quantity,
            # you won't be able to send another a different quantity for the first hour.
            # Dimensions can only be reported once per hour.
            # We are avoiding this problem here
            if (dry_run):
                responses += [self._meter_usage(dimension=d, dry_run=dry_run)]
            else:
                if not (self._initializing and d.quantity == 0):
                    responses += [
                        self._meter_usage(dimension=d, dry_run=dry_run)
                    ]
                if (self._initializing):
                    logger.info(f"setting _initializing to False")
                    self._initializing = False
        return responses

    def get_status(self):
        """Gets the state of the integration component and the consumption (number of requests) that hasn't been sent to the metering service yet"""
        return {
            "version": "1.0.0",
            "consumption": self.get_consumption(),
            "state": self.get_state()
        }

    def update_state(self):
        self.state.update_type(self._dimensions_storage.max_timestamp())

    def add_dimension_quantity(self, dimension_name, quantity):
        self._dimensions_storage.add_dimension_quantity(
            Dimension(dimension_name), quantity)

    def _check_connectivity_and_dimensions(self):
        """ Checks the connectivity and the dimensions given sending a dry_run call to the Marketplace Metering Service """
        self.meter_usages(dry_run=True)

    # Send the given dimension and quantity to Marketplace Metering Serverice
    # using the meter_usage method. If the dimension is sent successfully,
    # the quantity for the dimension is reset to 0 in the DB
    # (Only if dry_run is false)
    def _meter_usage(self, dimension, dry_run=False):
        logger.info(f"_metering_usage:  {dimension} ")

        utc_now = datetime.utcnow()
        try:
            response = self._mms_client.meter_usage(
                ProductCode=self._product_code,
                Timestamp=utc_now,
                UsageDimension=dimension.name,
                UsageQuantity=int(dimension.quantity),
                DryRun=dry_run)
            status_code = response["ResponseMetadata"]["HTTPStatusCode"]
            if (not dry_run and status_code == 200):
                self._dimensions_storage.reset_dimensions_quantity(dimension)
                self.state.discard_dimension_errors(dimension.name)
            return response

        except ClientError as err:
            if (dry_run):
                raise
            self.state.add_error(err)
            logger.error(err)
        except:
            if (dry_run):
                raise
            self.state.add(f"{sys.exc_info()[1]}")
            logger.error((f"{sys.exc_info()[1]}"))


class AbstractDimensionsStorage(ABC):
    @abstractmethod
    def get_dimensions(self):
        """ Returns a list with all dimensions """
        raise NotImplementedError()

    @abstractmethod
    def add_dimension_quantity(self, dimension, quantity):
        """ Adds the quantity given to the quantity in the DB for the given dimension """
        raise NotImplementedError()

    @abstractmethod
    def reset_dimensions_quantity(self, dimension):
        """ Sets the dimension's quantity to 0 and updates the timestamp to now """
        raise NotImplementedError()

    @abstractmethod
    def max_timestamp(self):
        """ Returns the most recent timestamp of all dimensions """
        raise NotImplementedError()


class DyDBDimensionsStorage(AbstractDimensionsStorage):

    NAME = "name"
    QUANTITY = "quantity"
    TIMESTAMP = "last_sent"

    def __init__(self,
                 region_name,
                 dimensions_table_name,
                 dimension_names,
                 delete_dimensions=False):
        self._dimensions_table_name = dimensions_table_name
        self._client = boto3.client('dynamodb', region_name=region_name)
        self._create_dimensions_table()
        self._dimensions_table = boto3.resource(
            'dynamodb',
            region_name=region_name).Table(self._dimensions_table_name)
        self._delete_dimensions = delete_dimensions
        self._init_dimensions_table(dimension_names)

    # if the table doesn't exists, it creates it
    def _create_dimensions_table(self):
        try:
            self._client.create_table(TableName=self._dimensions_table_name,
                                      KeySchema=[{
                                          'AttributeName': self.NAME,
                                          'KeyType': 'HASH'
                                      }],
                                      AttributeDefinitions=[{
                                          'AttributeName':
                                          self.NAME,
                                          'AttributeType':
                                          'S'
                                      }],
                                      ProvisionedThroughput={
                                          'ReadCapacityUnits': 1,
                                          'WriteCapacityUnits': 1
                                      })
            waiter = self._client.get_waiter('table_exists')
            waiter.wait(TableName=self._dimensions_table_name)
        except self._client.exceptions.ResourceInUseException:
            logger.info("table already existed")

    # This function will add the dimensions provided to the Marketplace
    # Integration module to the dimensions tables in DynamoDB
    def _init_dimensions_table(self, dimension_names):
        if (self._delete_dimensions):
            logger.info("deleting dimensions")
            for dn in self._get_dimensions_name():
                self._dimensions_table.delete_item(Key={self.NAME: dn})

        utcnow = datetime.utcnow()
        for d in dimension_names:
            response = self._dimensions_table.query(
                KeyConditionExpression=Key(self.NAME).eq(d))
            if not response["Count"]:
                logger.info("adding dimension:" + d)
                self._dimensions_table.put_item(
                    Item={
                        self.NAME: d,
                        self.QUANTITY: 0,
                        self.TIMESTAMP: int(utcnow.timestamp())
                    })

    def get_dimensions(self):
        """ Returns a list with all dimensions """
        dimensions = self._dimensions_table.scan()["Items"]
        result = []
        for d in dimensions:
            result += [
                Dimension(d[self.NAME], d[self.QUANTITY], d[self.TIMESTAMP])
            ]
        return result

    def _get_dimensions_name(self):
        """ Returns a list with the names of all dimensions """
        dimensions = self._dimensions_table.scan()["Items"]
        result = []
        for d in dimensions:
            result += [d[self.NAME]]
        return result

    def add_dimension_quantity(self, dimension, quantity):
        """ Adds the quantity given to the quantity in the DB for the given dimension """
        logger.info(
            f"add_dimension_quantity {dimension}, new quantity: [{quantity}]")
        updated_dimension = self._dimensions_table.query(
            KeyConditionExpression=Key(self.NAME).eq(
                dimension.name))["Items"][0]
        dim = Dimension(name=updated_dimension[self.NAME],
                        quantity=updated_dimension[self.QUANTITY],
                        timestamp=updated_dimension[self.TIMESTAMP])
        dim.quantity += quantity
        self._update_dimension(dim)

    def _update_dimension(self, dimension):
        self._dimensions_table.update_item(
            Key={self.NAME: dimension.name},
            UpdateExpression=f"SET {self.QUANTITY} = :q, {self.TIMESTAMP} =:ls",
            ExpressionAttributeValues={
                ':q': dimension.quantity,
                ':ls': dimension.timestamp
            })

    def reset_dimensions_quantity(self, dimension):
        """ Sets the dimension's quantity to 0 and updates the timestamp to now """
        logger.info(f"reset_dimensions_quantity {dimension}")
        dimension.quantity = 0
        dimension.timestamp = int(datetime.utcnow().timestamp())
        self._update_dimension(dimension)

    def max_timestamp(self):
        """ Returns the most recent timestamp of all dimensions """
        timestamps = self._dimensions_table.scan(
            ProjectionExpression=self.TIMESTAMP, )["Items"]
        max_timestamp = int(max(i[self.TIMESTAMP] for i in timestamps))
        return (max_timestamp)


class Dimension:
    def __init__(self, name, quantity=0, timestamp=0):
        self.name = name
        self.quantity = int(quantity)
        if timestamp == 0:
            timestamp = datetime.utcnow().timestamp()
        self.timestamp = int(timestamp)
        self.datetime = datetime.fromtimestamp(self.timestamp).isoformat()

    def __str__(self):
        return (
            f"Dimension: Name: [{self.name}], Quantity: [{self.quantity}], Timestamp: [{self.timestamp}], Datetime: [{self.datetime}]"
        )


class State():
    def __init__(self,
                 max_send_stop,
                 max_send_warning,
                 send_usage_after,
                 detail=None):
        self.max_send_stop = max_send_stop
        self.max_send_warning = max_send_warning
        if detail is None:
            detail = set()
        self.details = detail
        self.type = ""
        self._send_usage_after = send_usage_after

    def update_type(self, max_timestamp):
        if self.type != "init":
            utcnow = datetime.utcnow().timestamp()
            if max_timestamp <= (utcnow -
                                 self.max_send_stop * self._send_usage_after):
                self.type = "stop"
            elif max_timestamp <= (
                    utcnow - self.max_send_warning * self._send_usage_after):
                self.type = "warning"
            else:
                self.type = ""
                self.details = set()

    def add(self, detail):
        self.details.add(detail)

    def value(self):
        return (len(self.details) > 0)

    def add_error(self, error):
        self.add(error.response["Error"]["Code"] + ": " +
                 error.response["Error"]["Message"])

    def discard_dimension_errors(self, dimension_name):
        for detail in self.details.copy():
            if (f"usageDimension: {dimension_name}" in detail):
                self.details.discard(detail)
        if (len(self.details) == 0):
            self.type = ""


class Utils:
    @staticmethod
    def _json_serial(obj):
        if isinstance(obj, Decimal):
            return int(obj)
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, Dimension):
            return {
                "name": obj.name,
                "quantity": obj.quantity,
                "timestamp": obj.timestamp,
                "datetime": obj.datetime
            }
        if isinstance(obj, State):
            return {
                "value": obj.value(),
                "details": list(obj.details),
                "type": obj.type
            }
        raise TypeError("Type %s not serializable" % type(obj))

    @staticmethod
    def sanitize(obj):
        return json.loads(json.dumps(obj, default=Utils._json_serial))
