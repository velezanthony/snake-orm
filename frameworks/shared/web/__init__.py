"""Framework-agnostic pieces of the WEB layer: what every demo's shell needs and none of them owns.

It is the layer above the view models and below the templates, and the line between it and the
framework is the same one the rest of `shared` draws: what is written here is what does not change
when the router does. Today that is the catalogue of sections in `nav`; what will never be here is a
URL, a request or a response.
"""
