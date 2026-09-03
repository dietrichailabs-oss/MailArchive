from mailarchive.viewer.server import ArchiveViewer

def test_viewer_binds_ipv4_loopback_only(tmp_path):
    v=ArchiveViewer(tmp_path); host,port=v.start()
    try:
        assert host=='127.0.0.1'
        assert port>0
    finally:
        v.server.server_close()
