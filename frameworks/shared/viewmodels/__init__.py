"""VIEW MODELS: the flat shape one page reads, built once for every framework that renders it.

The layer sits between the use cases and the templates — `models -> selectors/services -> usecases
-> viewmodels -> the framework's template` — and it exists for two measured reasons rather than for
symmetry.

The first is that the two SSR demos were each building their own dicts, with different shapes, out of
the same use case. That makes a second set of templates cost the shape as well as the HTML, and a
shape copied twice is a shape that drifts: the lab had already got there, assembling its sections in
`shared/usecases/lab_usecases.py` for the API and again in `flask/apps/lab/urls.py` for the SSR, with
the column headers translated on one side and left in Spanish on the other.

The second is the one that costs queries. A template that walks `stock.sku.name` is loading a
RELATION inside the renderer, which is the one layer no `assert_queries` watches: it works today
because the selector did the `include`, and the day somebody drops that `include` the page still
paints — with a query per row, in production, silently. So the navigation happens here, where a test
can count it, and what reaches the template is `str`, `int` and `bool`.

Nothing here knows a URL, a request or a response. Ids travel so a template can build its own links
with its own tag, and that is as close to the web as this layer gets.
"""
