python-spot documentation
==========================

Welcome to the python-spot documentation. The project provides an
asynchronous client that wraps the SPOT device feed API.

Quick start
-----------

Each ``SpotApi`` instance manages one or more feed credentials and populates a
``SpotFeed`` model with messages retrieved from SPOT. Fetching the latest
messages can be as simple as:

.. code-block:: python

   import asyncio
   from spot_api import SpotApi


   async def main():
       async with SpotApi([("<feed-id>", "<password>")]) as api:
           await api.request_latest()

           for message in api.feed.get_latest_messages():
               print(message.messenger_name, message.get_location())


   asyncio.run(main())

The API enforces a 150 second wait between requests to the same feed and a
shorter pause between different feeds. When those windows have not elapsed the
client will yield a ``SpotRequestStatus.THROTTLED`` result with the number of
seconds to wait before retrying. Iterating ``SpotApi.request_all_pages`` handles
this automatically by applying exponential backoff that never exceeds SPOT's
recommended limits.

``SpotFeed`` and ``SpotMessage`` expose convenience helpers that surface the
most common inspection patterns:

* ``SpotFeed.get_latest_messages()`` returns the newest message for each device
  contained in the feed.
* ``SpotFeed.iter_messages()`` and ``iter_messages_by_type()`` let you traverse
  the history while optionally filtering by message type.
* ``SpotMessage.get_location()`` formats the latitude, longitude, and altitude
  into a single descriptive string.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   api_reference

.. seealso::

   The official SPOT public API reference is available on the
   `findmespot support site <https://www.findmespot.com/en-us/support/spot-gen4/get-help/general/public-api-and-xml-feed>`_.
