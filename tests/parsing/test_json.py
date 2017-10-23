"""
This test module has tests relating to parser classes
"""

import os
import json

import pytest

import pygaps


@pytest.fixture
def basic_isotherm_json(basic_pointisotherm):
    """
    Gives a json of the isotherm from model data
    """

    isotherm_dict = basic_pointisotherm.to_dict()
    isotherm_dict.update({'id': basic_pointisotherm.id})

    isotherm_data_dict = basic_pointisotherm.data().to_dict(orient='index')
    isotherm_data_dict = [{p: str(t) for p, t in v.items()}
                          for k, v in isotherm_data_dict.items()]
    isotherm_dict["isotherm_data"] = isotherm_data_dict

    return json.dumps(isotherm_dict, sort_keys=True)


class TestJson(object):
    def test_isotherm_to_json(self, basic_pointisotherm, basic_isotherm_json):
        """Tests the parsing of an isotherm to json"""

        test_isotherm_json = pygaps.isotherm_to_json(basic_pointisotherm)

        assert basic_isotherm_json == test_isotherm_json

        return

    def test_isotherm_from_json(self, basic_pointisotherm, basic_isotherm_json):

        test_isotherm = pygaps.isotherm_from_json(basic_isotherm_json)
        assert basic_pointisotherm == test_isotherm

        return

    def test_isotherm_from_json_nist(self):

        JSON_PATH_NIST = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'docs', 'examples', 'data', 'parsing', 'nist', 'nist_iso.json')

        with open(JSON_PATH_NIST) as file:
            pygaps.isotherm_from_json(file.read(), fmt='NIST')

        return
