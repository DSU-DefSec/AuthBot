<!DOCTYPE html>
<?php
$creds = json_decode(file_get_contents("creds.json"));
/**
 * @return string
 */
function verify(): string {
    global $creds;
    if (!(isset($_GET["state"]) && isset($_GET["code"]))) return "Invalid request 😢";

    try {
        preg_match("/\w{16}/", $_GET["state"], $state);
        preg_match("/[a-zA-Z0-9._-]+/", $_GET["code"], $code);
        if (!$state || !$code) {
            http_response_code(400);
            return "Invalid request<br>Pls no hak me 😢";
        }
        $state = $state[0];
        $code = $code[0];

        try {
            $db = $creds->db;
            @$connection = new mysqli($db->host, $db->user, $db->password, $db->db);
            if ($connection->connect_errno) throw new Exception("Error: $connection->connect_errno: $connection->connect_error");
        } catch (Throwable $e) {
            http_response_code(500);
            return "Server Error!<br>I lost my database ¯\_(ツ)_/¯";
        }

        $statement = $connection->prepare("update oauth set authorization_code = ? where state = ?;");
        $statement->bind_param("ss", $code, $state);
        $statement->execute();
        if ($statement->affected_rows < 1) {
            http_response_code(400);
            return "Invalid or expired code 🙁";
        }
        try {
            $socket = socket_create(AF_INET, SOCK_STREAM, SOL_TCP);
            socket_connect($socket, "localhost", 8888);
            socket_write($socket, $state, strlen($state));
            // socket_set_timeout($socket, 1);
//            socket_set_option($socket, SOL_SOCKET, SO_RCVTIMEO, ["sec" => 1, "usec" => 0]);
            echo "<" . socket_read($socket, 10) . ">";
            if (!$response = socket_read($socket, 1)) throw new Exception("Error: Could not read from socket");
            socket_close($socket);
            if ($response === "x") throw new Exception("Error: Did not verify");
        } catch (Throwable $e) {
            http_response_code(500);
            return "Could not process request 😬";
        }
        http_response_code(200);
        return "Verified 👍";

    } catch (Exception $e) {
        http_response_code(400);
        return "Invalid request 😢";
    }
}

?>
<html lang="en">
<head>
    <title>DSU Verification</title>
    <style>
        body {
            background: #004165;
        }

        .center {
            position: absolute;
            left: 50%;
            top: 30%;
            transform: translate(-50%, -50%);
            text-align: center;
            color: #ffffff;
        }

        .center > * {
            margin: 0;
        }

        #main {
            background: #ADAFAF;
            border-radius: 10px;
            padding: 15px;
        }
    </style>
</head>
<body>
<div class="center" id="main"><h1><?php print(verify()); ?></h1></div>
</body>
</html>