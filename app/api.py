#!/usr/bin/python

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import logging
from flask import Flask
from flask_restplus import Api, Resource

from marketplace import DyDBDimensionsStorage, MeterUsageIntegration


class Config(object):
    REGION = os.environ["AWS_REGION"]
    PRODUCT_CODE = os.environ["PRODUCT_CODE"]
    DIMENSIONS_TABLE_NAME = os.environ["DIMENSIONS_TABLE"]
    VERSION = os.environ["PRODUCT_VERSION"]
    # You can add additional dimensions. They will be created automatically
    # DIMENSIONS_NAMES = ["Requests", "Dimension2"]
    DIMENSIONS_NAMES = ["Requests"]
    # This will delete all the dimensions on the DimensionStorage at start time.
    # This is only useful for debuging
    DELETE_DIMENSIONS = True
    LOGGING_LEVEL = logging.INFO
    LOGGING_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    LOGGING_DATEFORMAT = "%Y-%m-%d %I:%M:%S %p"


logging.basicConfig(level=Config.LOGGING_LEVEL,
                    datefmt=Config.LOGGING_DATEFORMAT,
                    format=Config.LOGGING_FORMAT)

app = Flask(__name__)

api = Api(
    app,
    version=Config.VERSION,
    title="Sample metered container product",
    description=
    "This is a sample container product that integrates with AWS Marketplace Metering Service (MMS) to implement a metered pricing model. The product is charged based on the number of requests done to my-product-method"
)
ns = api.namespace('mcp', description='Sample metered container product')
mpns = api.namespace('awsmp', description='AWS Marketplace Integration')

# This is the storage object. It implements the AbstractDimensionsStorage class.
# This objects take care of persisting the dimensions. This implementation uses
# DynamoDB but if you would like to use other Storage type (RDS, S3, etc)
# you can extend the abstract for your storage. Later just provide the new object
# while instanciating the MeterUsageIntegration class
dimensions_storage = DyDBDimensionsStorage(
    region_name=Config.REGION,
    dimensions_table_name=Config.DIMENSIONS_TABLE_NAME,
    dimension_names=Config.DIMENSIONS_NAMES,
    delete_dimensions=Config.DELETE_DIMENSIONS)

# Marketplace metering integration
maketplace_integration = MeterUsageIntegration(Config.REGION,
                                               Config.PRODUCT_CODE,
                                               dimensions_storage)

# This is the sample method you want to sell


@ns.route('/my-product-method')
@ns.response(400, "Error")
class MyClass(Resource):

    messages = {
        "": {},
        "init": {
            "message": "Problems initializing the product"
        },
        "stop": {
            "message":
            "The AWS Marketplace's Metering Service is not reachable. Please check the container's connectivity and restart the application"
        },
        "warning": {
            "warning":
            "Metering information hasn't been sent to AWS Marketplace. Please check the container's connectivity. If meetering information is not send to AWS Marketplace the product will stop working"
        }
    }

    def get(self):
        """Sample method charged by the number of requests"""
        result = {}
        result_code = 200

        if maketplace_integration.state.type == "" or maketplace_integration.state.type == "warning":
            result = {"my-product-method": "Hello AWS Marketplace!"}
            maketplace_integration.add_dimension_quantity(
                Config.DIMENSIONS_NAMES[0], 1)
            result = {
                **result,
                **self.messages[maketplace_integration.state.type]
            }
        else:
            result = {
                **result,
                **self.messages[maketplace_integration.state.type]
            }
            result["details"] = list(maketplace_integration.state.details)
            result_code = 400
        return (result, result_code)


@mpns.route('/send-metering')
class Metering(Resource):
    def get(self):
        """Allows to manually send the consumption information to the metering service"""
        return {
            "meter_usages_responses": maketplace_integration.meter_usages(),
            "status": maketplace_integration.get_status()
        }


@mpns.route('/status')
class Status(Resource):
    def get(self):
        """Gets the internal state of the integration component and the consumption (number of requests) that hasn't been sent to the metering service"""
        return maketplace_integration.get_status()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
