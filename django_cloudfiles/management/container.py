import os
import cloudfiles
from django.core.management.base import CommandError
from django_cloudfiles import is_ignored_path, URL_SEPERATOR
from django_cloudfiles.management.utils.string import write
from django_cloudfiles.management.utils.progress_bar import ProgressBar
from .cloudfile import CloudFile

def check_public(container, make_public=False):
    """
    Returns true if:
     1) The container is public, or
     2) The container is made public using the make_public param
    """
    if container.is_public():
        return True
    if make_public:
        write("Making container public: ")
        try:
            container.make_public()
            print "done"
            return True
        except CDNNotEnabled:
            print "failed (CDN is not available for your account)."
    print ("*** WARNING: Container is not public. Ensure that it's " +
           "made public, or your files will not be available over " +
           "the CDN. You can use the --make-public option to allow " +
           "this script to make the container public for you.")
    return False

def check_uri(container, media_url):
    public_uri = container.public_uri() + '/'
    if media_url != public_uri:
        print "In your settings.py file, be sure to set:"
        print "    MEDIA_URL = '%s'" % public_uri
        print "  (currently) = '%s'" % media_url

def upload_tree(container, tree_root, force=False, drop_remote_prefix=None,
                verbosity=1):
    """
    Upload a tree of files rooted at tree_root to a specified container,
    skipping any local paths that match a pattern in IGNORE_PATTERNS_FLAGS.
    Symbolic links are followed, so make sure you don't have any loops!

    Remote file names are the local file names with seperator changed to
    URL_SEPERATOR and the tree_root dropped from the beginning.

    Returns the number of files uploaded and total bytes transfered (tuple).
    """
    count = 0
    bytes = 0

    # clean up given path
    tree_root = os.path.abspath(tree_root)
    tree_root = os.path.normpath(tree_root)

    # make sure tree root exists and is a directory
    if not (os.path.exists(tree_root) and
            os.path.isdir(tree_root)):
        raise CommandError("Not a valid directory: " + tree_root)

    # no drop-prefix set yet; defalt to the tree root
    if not drop_remote_prefix:
        drop_remote_prefix = tree_root

    # walk the tree, skipping ignored directories
    for root, dirs, files in os.walk(tree_root):
        if is_ignored_path(root):
            if verbosity > 1:
                print "  IGNORING: %s" % root
            continue

        # loop over files in this directory
        for filename in files:
            path = os.path.join(root, filename)

            # ignored file: skip
            if is_ignored_path(path):
                if verbosity > 1:
                    print "  IGNORING: %s" % path
                continue

            # set remote filename
            remote_filename = path[len(drop_remote_prefix)+1:]
            if os.sep != URL_SEPERATOR:
                remote_filename.replace(os.sep, URL_SEPERATOR)

            # uplaod file if it has changed (or we force it)
            cf = CloudFile(container, remote_filename, path)
            if force or cf.has_changed():
                bytes += cf.upload(verbosity)
                count += 1
            elif verbosity > 1:
                print "  SKIPPING: %s" % path

        # os.walk doesn't follow linked subdirectories (potential infinite
        # loop) before Python 2.6, so we recurse over them manually:
        for dir in dirs:
            path = os.path.join(root, dir)
            if os.path.islink(path):
                stats = upload_tree(container, path, force, drop_remote_prefix,
                                    verbosity)
                count += stats[0]
                bytes += stats[1]

    return count, bytes

def download(container, root, force=False, prefix='', verbosity=1):
    """
    Pull all files from container into the root directory.
    
    """
    count = 0
    bytes = 0
    
    # clean up given path
    root = os.path.abspath(root)
    root = os.path.normpath(root)
    
    # make sure tree root exists and is a directory
    if not (os.path.exists(root) and
            os.path.isdir(root)):
        raise CommandError("Not a valid directory: " + root)
        
    for o in container.get_objects(prefix=prefix):         
        filename = os.path.join(root, o.name)
        exists = os.path.exists(filename)
        local_size = os.path.getsize(filename) if exists else 0
        path = os.path.dirname(filename)
        
        if not os.path.exists(path):
            os.makedirs(path, 0755)
            
        if verbosity > 0:    
            print "  %s:" % o.name
            progress_bar = ProgressBar(total_ticks=73)
            progress_bar.start()
            callback = progress_bar.tick
        else:
            callback = None
        
        if (not exists or force) or (local_size != o.size):
            try:
                o.save_to_filename(filename, callback=callback)
                count += 1
                bytes += os.path.getsize(filename)
            except IOError, (errno, string):
                print ""
                raise CommandError("Problem downloading file '" + filename +
                                   "': " + string + " (IOError " + str(errno) + ")")
            except cloudfiles.errors.InvalidObjectSize:
                print ""
                raise CommandError("Invalid size for file: " + filename)
        if verbosity > 0:
            progress_bar.end()

    return (count, bytes)