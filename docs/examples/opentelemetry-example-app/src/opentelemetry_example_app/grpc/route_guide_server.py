#!/usr/bin/env python
# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=import-error
# pylint: disable=invalid-name

"""The Python implementation of the gRPC route guide server.

Note that you need ``opentelemetry-instrumentation-grpc`` and ``protobuf`` to be installed
to run these examples. To run this script in the context of the example app,
install ``opentelemetry-example-app``::

    pip install -e ext/opentelemetry-instrumentation-grpc/
    pip install -e docs/examples/opentelemetry-example-app

Then run the server in one shell::

    python -m opentelemetry_example_app.grpc.route_guide_server

and the client in another::

    python -m opentelemetry_example_app.grpc.route_guide_client

See also:
https://github.com/grpc/grpc/tree/master/examples/python/route_guide
"""

import logging
import math
import time
from concurrent import futures

import grpc

from opentelemetry import trace
from opentelemetry.instrumentation.grpc import server_interceptor
from opentelemetry.instrumentation.grpc.grpcext import intercept_server
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleExportSpanProcessor,
)

try:
    # Relative imports should work in the context of the package, e.g.:
    # `python -m opentelemetry_example_app.grpc.route_guide_server`.
    from .gen import route_guide_pb2, route_guide_pb2_grpc
    from . import route_guide_resources
except ImportError:
    # This will fail when running the file as a script, e.g.:
    # `./route_guide_server.py`
    # fall back to importing from the same directory in this case.
    from gen import route_guide_pb2, route_guide_pb2_grpc
    import route_guide_resources

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    SimpleExportSpanProcessor(ConsoleSpanExporter())
)


def get_feature(feature_db, point):
    """Returns Feature at given location or None."""
    for feature in feature_db:
        if feature.location == point:
            return feature
    return None


def get_distance(start, end):
    """Distance between two points."""
    coord_factor = 10000000.0
    lat_1 = start.latitude / coord_factor
    lat_2 = end.latitude / coord_factor
    lon_1 = start.longitude / coord_factor
    lon_2 = end.longitude / coord_factor
    lat_rad_1 = math.radians(lat_1)
    lat_rad_2 = math.radians(lat_2)
    delta_lat_rad = math.radians(lat_2 - lat_1)
    delta_lon_rad = math.radians(lon_2 - lon_1)

    # Formula is based on http://mathforum.org/library/drmath/view/51879.html
    a = pow(math.sin(delta_lat_rad / 2), 2) + (
        math.cos(lat_rad_1)
        * math.cos(lat_rad_2)
        * pow(math.sin(delta_lon_rad / 2), 2)
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    R = 6371000
    # metres
    return R * c


class RouteGuideServicer(route_guide_pb2_grpc.RouteGuideServicer):
    """Provides methods that implement functionality of route guide server."""

    def __init__(self):
        self.db = route_guide_resources.read_route_guide_database()

    def GetFeature(self, request, context):
        feature = get_feature(self.db, request)
        if feature is None:
            return route_guide_pb2.Feature(name="", location=request)
        return feature

    def ListFeatures(self, request, context):
        left = min(request.lo.longitude, request.hi.longitude)
        right = max(request.lo.longitude, request.hi.longitude)
        top = max(request.lo.latitude, request.hi.latitude)
        bottom = min(request.lo.latitude, request.hi.latitude)
        for feature in self.db:
            if (
                feature.location.longitude >= left
                and feature.location.longitude <= right
                and feature.location.latitude >= bottom
                and feature.location.latitude <= top
            ):
                yield feature

    def RecordRoute(self, request_iterator, context):
        point_count = 0
        feature_count = 0
        distance = 0.0
        prev_point = None

        start_time = time.time()
        for point in request_iterator:
            point_count += 1
            if get_feature(self.db, point):
                feature_count += 1
            if prev_point:
                distance += get_distance(prev_point, point)
            prev_point = point

        elapsed_time = time.time() - start_time
        return route_guide_pb2.RouteSummary(
            point_count=point_count,
            feature_count=feature_count,
            distance=int(distance),
            elapsed_time=int(elapsed_time),
        )

    def RouteChat(self, request_iterator, context):
        prev_notes = []
        for new_note in request_iterator:
            for prev_note in prev_notes:
                if prev_note.location == new_note.location:
                    yield prev_note
            prev_notes.append(new_note)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    server = intercept_server(server, server_interceptor())

    route_guide_pb2_grpc.add_RouteGuideServicer_to_server(
        RouteGuideServicer(), server
    )
    server.add_insecure_port("[::]:50051")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig()
    serve()