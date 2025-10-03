#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <winsock2.h>
#include <ws2tcpip.h>

#define APP_MAX_BUFFER 1024
#define PORT 8080

int main() {
    WSADATA wsaData;

    // Initialize Winsock
    if (WSAStartup(MAKEWORD(2,2), &wsaData) != 0) {
        printf("WSAStartup failed.\n");
        return 1;
    }

    int server_fd, client_fd;
    struct sockaddr_in address;
    int addrlen = sizeof(address);
    char buffer[APP_MAX_BUFFER] = {0};

    // Create socket
    server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd == INVALID_SOCKET) {
        printf("Socket creation failed.\n");
        WSACleanup();
        return 1;
    }

    // Bind socket
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(PORT);

    if (bind(server_fd, (struct sockaddr*)&address, sizeof(address)) == SOCKET_ERROR) {
        printf("Bind failed.\n");
        closesocket(server_fd);
        WSACleanup();
        return 1;
    }

    // Listen
    if (listen(server_fd, 10) == SOCKET_ERROR) {
        printf("Listen failed.\n");
        closesocket(server_fd);
        WSACleanup();
        return 1;
    }

    printf("Server listening on port %d...\n", PORT);

    while (1) {
        printf("\nWaiting for a connection...\n");
        client_fd = accept(server_fd, (struct sockaddr*)&address, &addrlen);
        if (client_fd == INVALID_SOCKET) {
            printf("Accept failed.\n");
            continue;
        }

        // Receive data
        int bytes = recv(client_fd, buffer, APP_MAX_BUFFER - 1, 0);
        if (bytes > 0) {
            buffer[bytes] = '\0'; // Null-terminate
            printf("Received request:\n%s\n", buffer);
        }

        // Send HTTP response
        char *http_response = "HTTP/1.1 200 OK\r\n"
                              "Content-Type: text/plain\r\n"
                              "Content-Length: 13\r\n\r\n"
                              "Hello world!\n";

        send(client_fd, http_response, strlen(http_response), 0);

        // Close client socket
        closesocket(client_fd);
    }

    // Close server socket and cleanup
    closesocket(server_fd);
    WSACleanup();
    return 0;
}