#!/usr/bin/python

# Copyright (c) 2009-2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A CherryPy-based webserver to host images and build packages."""

import cherrypy
import optparse
import os
import sys

import autoupdate

# Sets up global to share between classes.
global updater
updater = None

def _GetConfig(options):
  """Returns the configuration for the devserver."""
  base_config = { 'global':
                  { 'server.log_request_headers': True,
                    'server.protocol_version': 'HTTP/1.1',
                    'server.socket_host': '0.0.0.0',
                    'server.socket_port': int(options.port),
                    'server.socket_timeout': 6000,
                    'response.timeout': 6000,
                    'tools.staticdir.root': os.getcwd(),
                  },
                  '/update':
                  {
                    # Gets rid of cherrypy parsing post file for args.
                    'request.process_request_body': False,
                  },
                  # Sets up the static dir for file hosting.
                  '/static':
                  { 'tools.staticdir.dir': 'static',
                    'tools.staticdir.on': True,
                  },
                }
  return base_config


def _PrepareToServeUpdatesOnly(image_dir):
  """Sets up symlink to image_dir for serving purposes."""
  assert os.path.exists(image_dir), '%s must exist.' % image_dir
  # If  we're  serving  out  of  an archived  build  dir  (e.g.  a
  # buildbot), prepare this webserver's magic 'static/' dir with a
  # link to the build archive.
  cherrypy.log('Preparing autoupdate for "serve updates only" mode.',
               'DEVSERVER')
  if os.path.exists('static/archive'):
    if image_dir != os.readlink('static/archive'):
      cherrypy.log('removing stale symlink to %s' % image_dir, 'DEVSERVER')
      os.unlink('static/archive')
      os.symlink(image_dir, 'static/archive')
  else:
    os.symlink(image_dir, 'static/archive')
  cherrypy.log('archive dir: %s ready to be used to serve images.' % image_dir,
               'DEVSERVER')


class DevServerRoot:
  """The Root Class for the Dev Server.

  CherryPy works as follows:
    For each method in this class, cherrpy interprets root/path
    as a call to an instance of DevServerRoot->method_name.  For example,
    a call to http://myhost/build will call build.  CherryPy automatically
    parses http args and places them as keyword arguments in each method.
    For paths http://myhost/update/dir1/dir2, you can use *args so that
    cherrypy uses the update method and puts the extra paths in args.
  """

  def build(self, board, pkg):
    """Builds the package specified."""
    cherrypy.log('emerging %s' % pkg, 'BUILD')
    emerge_command = 'emerge-%s %s' % (board, pkg)
    err = os.system(emerge_command)
    if err != 0:
      raise Exception('failed to execute %s' % emerge_command)
    eclean_command = 'eclean-%s -d packages' % board
    err = os.system(eclean_command)
    if err != 0:
      raise Exception('failed to execute %s' % emerge_command)

  def index(self):
    return 'Welcome to the Dev Server!'

  def update(self, *args):
    label = '/'.join(args)
    body_length = int(cherrypy.request.headers['Content-Length'])
    data = cherrypy.request.rfile.read(body_length)
    return updater.HandleUpdatePing(data, label)

  # Expose actual methods.  Necessary to actually have these callable.
  build.exposed = True
  update.exposed = True
  index.exposed = True


if __name__ == '__main__':
  usage = 'usage: %prog [options]'
  parser = optparse.OptionParser(usage)
  parser.add_option('--archive_dir', dest='archive_dir',
                    help='serve archived builds only.')
  parser.add_option('--client_prefix', dest='client_prefix',
                    help='Required prefix for client software version.',
                    default='MementoSoftwareUpdate')
  parser.add_option('--factory_config', dest='factory_config',
                    help='Config file for serving images from factory floor.')
  parser.add_option('--image', dest='image',
                    help='Force update using this image.')
  parser.add_option('--port', default=8080,
                    help='Port for the dev server to use.')
  parser.add_option('-t', action='store_true', dest='test_image')
  parser.add_option('-u', '--urlbase', dest='urlbase',
                    help='base URL, other than devserver, for update images.')
  parser.add_option('--use_cached', action="store_true", default=False,
                    help='Prefer cached image regardless of timestamps.')
  parser.add_option('--validate_factory_config', action="store_true",
                    dest='validate_factory_config',
                    help='Validate factory config file, then exit.')
  parser.set_usage(parser.format_help())
  (options, _) = parser.parse_args()

  devserver_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
  root_dir = os.path.realpath('%s/../..' % devserver_dir)
  serve_only = False

  if options.archive_dir:
    static_dir = os.path.realpath(options.archive_dir)
    _PrepareToServeUpdatesOnly(static_dir)
    serve_only = True
  else:
    static_dir = os.path.realpath('%s/static' % devserver_dir)
    os.system('mkdir -p %s' % static_dir)

  cherrypy.log('Source root is %s' % root_dir, 'DEVSERVER')
  cherrypy.log('Serving from %s' % static_dir, 'DEVSERVER')

  updater = autoupdate.Autoupdate(
      root_dir=root_dir,
      static_dir=static_dir,
      serve_only=serve_only,
      urlbase=options.urlbase,
      test_image=options.test_image,
      factory_config_path=options.factory_config,
      client_prefix=options.client_prefix,
      forced_image=options.image,
      use_cached=options.use_cached,
      port=options.port)

  # Sanity-check for use of validate_factory_config.
  if not options.factory_config and options.validate_factory_config:
    parser.error('You need a factory_config to validate.')

  if options.factory_config:
    updater.ImportFactoryConfigFile(options.factory_config,
                                     options.validate_factory_config)
    # We don't run the dev server with this option.
    if options.validate_factory_config:
      sys.exit(0)

  cherrypy.quickstart(DevServerRoot(), config=_GetConfig(options))
