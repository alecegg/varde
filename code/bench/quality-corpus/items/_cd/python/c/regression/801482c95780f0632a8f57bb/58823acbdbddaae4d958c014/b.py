# SPDX-License-Identifier: BSD-3-Clause

def test_last_executed_query(self):
        """
        last_executed_query should not raise an exception even if no previous
        query has been run.
        """
        cursor = connection.cursor()
        connection.ops.last_executed_query(cursor, '', ())

# SPDX-License-Identifier: BSD-3-Clause

def test_bug_19457(self):
        """
        Regression test for #19457
        get_image_dimensions fails on some pngs, while Image.size is working good on them
        """
        img_path = os.path.join(os.path.dirname(upath(__file__)), "magic.png")
        size = images.get_image_dimensions(img_path)
        with open(img_path, 'rb') as fh:
            self.assertEqual(size, Image.open(fh).size)

# SPDX-License-Identifier: BSD-3-Clause

def test_layermap_unique_multigeometry_fk(self):
        "Testing the `unique`, and `transform`, geometry collection conversion, and ForeignKey mappings."
        # All the following should work.

        # Telling LayerMapping that we want no transformations performed on the data.
        lm = LayerMapping(County, co_shp, co_mapping, transform=False)

        # Specifying the source spatial reference system via the `source_srs` keyword.
        lm = LayerMapping(County, co_shp, co_mapping, source_srs=4269)
        lm = LayerMapping(County, co_shp, co_mapping, source_srs='NAD83')

        # Unique may take tuple or string parameters.
        for arg in ('name', ('name', 'mpoly')):
            lm = LayerMapping(County, co_shp, co_mapping, transform=False, unique=arg)

        # Now test for failures

        # Testing invalid params for the `unique` keyword.
        for e, arg in ((TypeError, 5.0), (ValueError, 'foobar'), (ValueError, ('name', 'mpolygon'))):
            self.assertRaises(e, LayerMapping, County, co_shp, co_mapping, transform=False, unique=arg)

        # No source reference system defined in the shapefile, should raise an error.
        if connection.features.supports_transform:
            self.assertRaises(LayerMapError, LayerMapping, County, co_shp, co_mapping)

        # Passing in invalid ForeignKey mapping parameters -- must be a dictionary
        # mapping for the model the ForeignKey points to.
        bad_fk_map1 = copy(co_mapping)
        bad_fk_map1['state'] = 'name'
        bad_fk_map2 = copy(co_mapping)
        bad_fk_map2['state'] = {'nombre': 'State'}
        self.assertRaises(TypeError, LayerMapping, County, co_shp, bad_fk_map1, transform=False)
        self.assertRaises(LayerMapError, LayerMapping, County, co_shp, bad_fk_map2, transform=False)

        # There exist no State models for the ForeignKey mapping to work -- should raise
        # a MissingForeignKey exception (this error would be ignored if the `strict`
        # keyword is not set).
        lm = LayerMapping(County, co_shp, co_mapping, transform=False, unique='name')
        self.assertRaises(MissingForeignKey, lm.save, silent=True, strict=True)

        # Now creating the state models so the ForeignKey mapping may work.
        State.objects.bulk_create([
            State(name='Colorado'), State(name='Hawaii'), State(name='Texas')
        ])

        # If a mapping is specified as a collection, all OGR fields that
        # are not collections will be converted into them.  For example,
        # a Point column would be converted to MultiPoint. Other things being done
        # w/the keyword args:
        #  `transform=False`: Specifies that no transform is to be done; this
        #    has the effect of ignoring the spatial reference check (because the
        #    county shapefile does not have implicit spatial reference info).
        #
        #  `unique='name'`: Creates models on the condition that they have
        #    unique county names; geometries from each feature however will be
        #    appended to the geometry collection of the unique model.  Thus,
        #    all of the various islands in Honolulu county will be in in one
        #    database record with a MULTIPOLYGON type.
        lm = LayerMapping(County, co_shp, co_mapping, transform=False, unique='name')
        lm.save(silent=True, strict=True)

        # A reference that doesn't use the unique keyword; a new database record will
        # created for each polygon.
        lm = LayerMapping(CountyFeat, co_shp, cofeat_mapping, transform=False)
        lm.save(silent=True, strict=True)

        # The county helper is called to ensure integrity of County models.
        self.county_helper()

# SPDX-License-Identifier: BSD-3-Clause

def test_close_connection(self):
        """
        Test that connection can be closed (even when not explicitly opened)
        """
        conn = mail.get_connection(username='', password='')
        conn.close()

def test_server_stopped(self):
        """
        Test that closing the backend while the SMTP server is stopped doesn't
        raise an exception.
        """
        backend = smtp.EmailBackend(username='', password='')
        backend.open()
        self.server.stop()
        backend.close()