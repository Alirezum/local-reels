import pytest


@pytest.mark.parametrize(
    ("relpath", "content", "media_type"),
    [
        ("root.mp4", b"0123456789", "video/mp4"),
        ("Alpha/nested/photo.PNG", b"photo", "image/png"),
        ("Alpha/first clip.MP4", b"first", "video/mp4"),
    ],
)
def test_full_media_response(client, library, relpath, content, media_type):
    response = client.get(library[relpath]["url"])
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == media_type
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize(
    ("header", "content", "content_range"),
    [
        ("bytes=2-5", b"2345", "bytes 2-5/10"),
        ("bytes=6-", b"6789", "bytes 6-9/10"),
        ("bytes=-3", b"789", "bytes 7-9/10"),
        ("bytes=7-100", b"789", "bytes 7-9/10"),
        ("bytes=-100", b"0123456789", "bytes 0-9/10"),
        ("bytes=0-0", b"0", "bytes 0-0/10"),
        (" bytes=1-2 ", b"12", "bytes 1-2/10"),
    ],
)
def test_valid_ranges(client, library, header, content, content_range):
    response = client.get("/videos/root.mp4", headers={"Range": header})
    assert response.status_code == 206
    assert response.content == content
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"


@pytest.mark.parametrize(
    "header",
    ["bytes=-", "bytes=abc-def", "items=0-1", "bytes=0-1,3-4", "bytes=1", "Bytes=0-1"],
)
def test_malformed_ranges(client, library, header):
    response = client.get("/videos/root.mp4", headers={"Range": header})
    assert response.status_code == 416
    assert response.json() == {"detail": "Invalid range"}
    assert "content-range" not in response.headers


@pytest.mark.parametrize("header", ["bytes=10-", "bytes=20-30", "bytes=5-2", "bytes=-0"])
def test_unsatisfiable_ranges(client, library, header):
    response = client.get("/videos/root.mp4", headers={"Range": header})
    assert response.status_code == 416
    assert response.content == b""
    assert response.headers["content-range"] == "bytes */10"
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize("header", [None, "bytes=0-", "bytes=0-0", "bytes=-1"])
def test_empty_file_responses(client, sandbox, header):
    (sandbox.media_dir / "empty.mp4").write_bytes(b"")
    response = client.get("/videos/empty.mp4", headers={"Range": header} if header else {})
    assert response.status_code == (416 if header else 200)
    assert response.content == b""
    assert response.headers["accept-ranges"] == "bytes"
    if header:
        assert response.headers["content-range"] == "bytes */0"
    else:
        assert response.headers["content-length"] == "0"


@pytest.mark.parametrize("header", [None, "bytes=0-1"])
def test_missing_files_and_directories(client, sandbox, header):
    (sandbox.media_dir / "directory.mp4").mkdir()
    for relpath in ("missing.mp4", "directory.mp4"):
        response = client.get(f"/videos/{relpath}", headers={"Range": header} if header else {})
        assert response.status_code == 404
        assert response.json() == {"detail": "Video not found"}


@pytest.mark.parametrize("header", [None, "bytes=0-1"])
def test_symlinks_cannot_serve_files_outside_media_directory(client, sandbox, header):
    outside = sandbox.root / "media-sibling"
    outside.mkdir()
    target = outside / "outside.mp4"
    target.write_bytes(b"outside data")
    (sandbox.media_dir / "linked.mp4").symlink_to(target)
    (sandbox.media_dir / "linked-directory").symlink_to(outside, target_is_directory=True)
    for relpath in ("linked.mp4", "linked-directory/outside.mp4"):
        response = client.get(f"/videos/{relpath}", headers={"Range": header} if header else {})
        assert response.status_code == 404
        assert response.json() == {"detail": "Video not found"}


def test_symlink_within_media_directory_is_served(client, sandbox):
    target = sandbox.media_dir / "original.mp4"
    target.write_bytes(b"inside")
    (sandbox.media_dir / "alias.mp4").symlink_to(target)
    response = client.get("/videos/alias.mp4")
    assert response.status_code == 200
    assert response.content == b"inside"
